import json
import logging

from botocore.config import Config
from botocore.exceptions import ClientError

from dataall.api.Objects.Stack import stack_helper
from dataall import db
from dataall.api.context import Context
from dataall.aws.handlers.service_handlers import Worker
from dataall.aws.handlers.sts import SessionHelper
from dataall.db import paginate, exceptions, models
from dataall.db.api import Environment, ResourcePolicy
from dataall.db.api.organization import Organization
from dataall.modules.dataset_sharing.db.models import ShareObject
from dataall.modules.datasets import Dataset
from dataall.modules.datasets.api.dataset.enums import DatasetRole
from dataall.modules.datasets.aws.glue_dataset_client import DatasetCrawler
from dataall.modules.datasets.db.dataset_location_repository import DatasetLocationRepository
from dataall.modules.datasets.db.dataset_service import DatasetService
from dataall.modules.datasets.indexers.dataset_indexer import DatasetIndexer
from dataall.modules.datasets.indexers.table_indexer import DatasetTableIndexer
from dataall.modules.datasets.services.dataset_permissions import CREDENTIALS_DATASET, SYNC_DATASET, SUMMARY_DATASET, \
    CRAWL_DATASET, DELETE_DATASET, SUBSCRIPTIONS_DATASET
from dataall.aws.handlers.quicksight import Quicksight

log = logging.getLogger(__name__)


def check_dataset_account(environment):
    if environment.dashboardsEnabled:
        quicksight_subscription = Quicksight.check_quicksight_enterprise_subscription(AwsAccountId=environment.AwsAccountId)
        if quicksight_subscription:
            group = Quicksight.create_quicksight_group(AwsAccountId=environment.AwsAccountId)
            return True if group else False
    return True


def create_dataset(context: Context, source, input=None):
    with context.engine.scoped_session() as session:
        environment = Environment.get_environment_by_uri(session, input.get('environmentUri'))
        check_dataset_account(environment=environment)

        dataset = DatasetService.create_dataset(
            session=session,
            username=context.username,
            groups=context.groups,
            uri=input.get('environmentUri'),
            data=input,
            check_perm=True,
        )
        DatasetService.create_dataset_stack(session, dataset)

        DatasetIndexer.upsert(
            session=session, dataset_uri=dataset.datasetUri
        )

    _deploy_dataset_stack(dataset)

    dataset.userRoleForDataset = DatasetRole.Creator.value

    return dataset


def import_dataset(context: Context, source, input=None):
    if not input:
        raise exceptions.RequiredParameter(input)
    if not input.get('environmentUri'):
        raise exceptions.RequiredParameter('environmentUri')
    if not input.get('bucketName'):
        raise exceptions.RequiredParameter('bucketName')
    if not input.get('SamlAdminGroupName'):
        raise exceptions.RequiredParameter('group')

    with context.engine.scoped_session() as session:
        environment = Environment.get_environment_by_uri(session, input.get('environmentUri'))
        check_dataset_account(environment=environment)

        dataset = DatasetService.create_dataset(
            session=session,
            username=context.username,
            groups=context.groups,
            uri=input.get('environmentUri'),
            data=input,
            check_perm=True,
        )
        dataset.imported = True
        dataset.importedS3Bucket = True if input['bucketName'] else False
        dataset.importedGlueDatabase = True if input.get('glueDatabaseName') else False
        dataset.importedKmsKey = True if input.get('KmsKeyId') else False
        dataset.importedAdminRole = True if input.get('adminRoleName') else False

        DatasetService.create_dataset_stack(session, dataset)

        DatasetIndexer.upsert(
            session=session, dataset_uri=dataset.datasetUri
        )

    _deploy_dataset_stack(dataset)

    dataset.userRoleForDataset = DatasetRole.Creator.value

    return dataset


def get_dataset(context, source, datasetUri=None):
    with context.engine.scoped_session() as session:
        dataset = DatasetService.get_dataset(session, uri=datasetUri)
        if dataset.SamlAdminGroupName in context.groups:
            dataset.userRoleForDataset = DatasetRole.Admin.value
        return dataset


def resolve_user_role(context: Context, source: Dataset, **kwargs):
    if not source:
        return None
    if source.owner == context.username:
        return DatasetRole.Creator.value
    elif source.SamlAdminGroupName in context.groups:
        return DatasetRole.Admin.value
    elif source.stewards in context.groups:
        return DatasetRole.DataSteward.value
    else:
        with context.engine.scoped_session() as session:
            share = (
                session.query(ShareObject)
                .filter(ShareObject.datasetUri == source.datasetUri)
                .first()
            )
            if share and (
                share.owner == context.username or share.principalId in context.groups
            ):
                return DatasetRole.Shared.value
    return DatasetRole.NoPermission.value


def get_file_upload_presigned_url(
    context, source, datasetUri: str = None, input: dict = None
):
    with context.engine.scoped_session() as session:
        dataset = DatasetService.get_dataset_by_uri(session, datasetUri)

    s3_client = SessionHelper.remote_session(dataset.AwsAccountId).client(
        's3',
        region_name=dataset.region,
        config=Config(signature_version='s3v4', s3={'addressing_style': 'virtual'}),
    )
    try:
        s3_client.get_bucket_acl(
            Bucket=dataset.S3BucketName, ExpectedBucketOwner=dataset.AwsAccountId
        )
        response = s3_client.generate_presigned_post(
            Bucket=dataset.S3BucketName,
            Key=input.get('prefix', 'uploads') + '/' + input.get('fileName'),
            ExpiresIn=15 * 60,
        )

        return json.dumps(response)
    except ClientError as e:
        raise e


def list_datasets(context: Context, source, filter: dict = None):
    if not filter:
        filter = {'page': 1, 'pageSize': 5}
    with context.engine.scoped_session() as session:
        return DatasetService.paginated_user_datasets(
            session, context.username, context.groups, uri=None, data=filter
        )


def list_locations(context, source: Dataset, filter: dict = None):
    if not source:
        return None
    if not filter:
        filter = {'page': 1, 'pageSize': 5}
    with context.engine.scoped_session() as session:
        return DatasetLocationRepository.paginated_dataset_locations(
            session=session,
            uri=source.datasetUri,
            data=filter,
        )


def list_tables(context, source: Dataset, filter: dict = None):
    if not source:
        return None
    if not filter:
        filter = {'page': 1, 'pageSize': 5}
    with context.engine.scoped_session() as session:
        return DatasetService.paginated_dataset_tables(
            session=session,
            username=context.username,
            groups=context.groups,
            uri=source.datasetUri,
            data=filter,
        )


def get_dataset_organization(context, source: Dataset, **kwargs):
    if not source:
        return None
    with context.engine.scoped_session() as session:
        return Organization.get_organization_by_uri(session, source.organizationUri)


def get_dataset_environment(context, source: Dataset, **kwargs):
    if not source:
        return None
    with context.engine.scoped_session() as session:
        return Environment.get_environment_by_uri(session, source.environmentUri)


def get_dataset_owners_group(context, source: Dataset, **kwargs):
    if not source:
        return None
    return source.SamlAdminGroupName


def get_dataset_stewards_group(context, source: Dataset, **kwargs):
    if not source:
        return None
    return source.stewards


def update_dataset(context, source, datasetUri: str = None, input: dict = None):
    with context.engine.scoped_session() as session:
        dataset = DatasetService.get_dataset_by_uri(session, datasetUri)
        environment = Environment.get_environment_by_uri(session, dataset.environmentUri)
        check_dataset_account(environment=environment)
        updated_dataset = DatasetService.update_dataset(
            session=session,
            uri=datasetUri,
            data=input,
        )
        DatasetIndexer.upsert(session, dataset_uri=datasetUri)

    _deploy_dataset_stack(updated_dataset)

    return updated_dataset


def get_dataset_statistics(context: Context, source: Dataset, **kwargs):
    if not source:
        return None
    with context.engine.scoped_session() as session:
        count_tables = DatasetService.count_dataset_tables(session, source.datasetUri)
        count_locations = DatasetLocationRepository.count_dataset_locations(
            session, source.datasetUri
        )
        count_upvotes = db.api.Vote.count_upvotes(
            session, None, None, source.datasetUri, {'targetType': 'dataset'}
        )
    return {
        'tables': count_tables or 0,
        'locations': count_locations or 0,
        'upvotes': count_upvotes or 0,
    }


def get_dataset_etl_credentials(context: Context, source, datasetUri: str = None):
    with context.engine.scoped_session() as session:
        ResourcePolicy.check_user_resource_permission(
            session=session,
            username=context.username,
            groups=context.groups,
            resource_uri=datasetUri,
            permission_name=CREDENTIALS_DATASET,
        )
        task = models.Task(targetUri=datasetUri, action='iam.dataset.user.credentials')
        session.add(task)
    response = Worker.process(
        engine=context.engine, task_ids=[task.taskUri], save_response=False
    )[0]
    return json.dumps(response['response'])


def get_dataset_assume_role_url(context: Context, source, datasetUri: str = None):
    with context.engine.scoped_session() as session:
        ResourcePolicy.check_user_resource_permission(
            session=session,
            username=context.username,
            groups=context.groups,
            resource_uri=datasetUri,
            permission_name=CREDENTIALS_DATASET,
        )
        dataset = DatasetService.get_dataset_by_uri(session, datasetUri)
        if dataset.SamlAdminGroupName not in context.groups:
            share = ShareObject.get_share_by_dataset_attributes(
                session=session,
                dataset_uri=datasetUri,
                dataset_owner=context.username
            )
            shared_environment = Environment.get_environment_by_uri(
                session=session,
                uri=share.environmentUri
            )
            env_group = Environment.get_environment_group(
                session=session,
                group_uri=share.principalId,
                environment_uri=share.environmentUri
            )
            role_arn = env_group.environmentIAMRoleArn
            account_id = shared_environment.AwsAccountId
        else:
            role_arn = dataset.IAMDatasetAdminRoleArn
            account_id = dataset.AwsAccountId

    pivot_session = SessionHelper.remote_session(account_id)
    aws_session = SessionHelper.get_session(
        base_session=pivot_session, role_arn=role_arn
    )
    url = SessionHelper.get_console_access_url(
        aws_session,
        region=dataset.region,
        bucket=dataset.S3BucketName,
    )
    return url


def sync_tables(context: Context, source, datasetUri: str = None):
    with context.engine.scoped_session() as session:
        ResourcePolicy.check_user_resource_permission(
            session=session,
            username=context.username,
            groups=context.groups,
            resource_uri=datasetUri,
            permission_name=SYNC_DATASET,
        )
        dataset = DatasetService.get_dataset_by_uri(session, datasetUri)

        task = models.Task(
            action='glue.dataset.database.tables',
            targetUri=dataset.datasetUri,
        )
        session.add(task)
    Worker.process(engine=context.engine, task_ids=[task.taskUri], save_response=False)
    with context.engine.scoped_session() as session:
        DatasetTableIndexer.upsert_all(
            session=session, dataset_uri=dataset.datasetUri
        )
        DatasetTableIndexer.remove_all_deleted(session=session, dataset_uri=dataset.datasetUri)
        return DatasetService.paginated_dataset_tables(
            session=session,
            username=context.username,
            groups=context.groups,
            uri=datasetUri,
            data={'page': 1, 'pageSize': 10},
            check_perm=None,
        )


def start_crawler(context: Context, source, datasetUri: str, input: dict = None):
    with context.engine.scoped_session() as session:
        ResourcePolicy.check_user_resource_permission(
            session=session,
            username=context.username,
            groups=context.groups,
            resource_uri=datasetUri,
            permission_name=CRAWL_DATASET,
        )

        dataset = DatasetService.get_dataset_by_uri(session, datasetUri)

        location = (
            f's3://{dataset.S3BucketName}/{input.get("prefix")}'
            if input.get('prefix')
            else f's3://{dataset.S3BucketName}'
        )

        crawler = DatasetCrawler(dataset).get_crawler()
        if not crawler:
            raise exceptions.AWSResourceNotFound(
                action=CRAWL_DATASET,
                message=f'Crawler {dataset.GlueCrawlerName} can not be found',
            )

        task = models.Task(
            targetUri=datasetUri,
            action='glue.crawler.start',
            payload={'location': location},
        )
        session.add(task)
        session.commit()

        Worker.queue(engine=context.engine, task_ids=[task.taskUri])

        return {
            'Name': dataset.GlueCrawlerName,
            'AwsAccountId': dataset.AwsAccountId,
            'region': dataset.region,
            'status': crawler.get('LastCrawl', {}).get('Status', 'N/A'),
        }


def list_dataset_share_objects(context, source, filter: dict = None):
    if not source:
        return None
    if not filter:
        filter = {'page': 1, 'pageSize': 5}
    with context.engine.scoped_session() as session:
        return DatasetService.paginated_dataset_shares(
            session=session,
            username=context.username,
            groups=context.groups,
            uri=source.datasetUri,
            data=filter,
            check_perm=True,
        )


def generate_dataset_access_token(context, source, datasetUri: str = None):
    with context.engine.scoped_session() as session:
        ResourcePolicy.check_user_resource_permission(
            session=session,
            username=context.username,
            groups=context.groups,
            resource_uri=datasetUri,
            permission_name=CREDENTIALS_DATASET,
        )
        dataset = DatasetService.get_dataset_by_uri(session, datasetUri)

    pivot_session = SessionHelper.remote_session(dataset.AwsAccountId)
    aws_session = SessionHelper.get_session(
        base_session=pivot_session, role_arn=dataset.IAMDatasetAdminRoleArn
    )
    c = aws_session.get_credentials()
    credentials = {
        'AccessKey': c.access_key,
        'SessionKey': c.secret_key,
        'sessionToken': c.token,
    }

    return json.dumps(credentials)


def get_dataset_summary(context, source, datasetUri: str = None):
    with context.engine.scoped_session() as session:
        dataset = DatasetService.get_dataset_by_uri(session, datasetUri)
        environment = Environment.get_environment_by_uri(
            session, dataset.environmentUri
        )

        pivot_session = SessionHelper.remote_session(dataset.AwsAccountId)
        env_admin_session = SessionHelper.get_session(
            base_session=pivot_session,
            role_arn=environment.EnvironmentDefaultIAMRoleArn,
        )
        s3 = env_admin_session.client('s3', region_name=dataset.region)

        try:
            s3.head_object(
                Bucket=environment.EnvironmentDefaultBucketName,
                Key=f'summary/{datasetUri}/summary.md',
            )
            response = s3.get_object(
                Bucket=environment.EnvironmentDefaultBucketName,
                Key=f'summary/{datasetUri}/summary.md',
            )
            content = str(response['Body'].read().decode('utf-8'))
            return content
        except Exception as e:
            raise e


def save_dataset_summary(
    context: Context, source, datasetUri: str = None, content: str = None
):
    with context.engine.scoped_session() as session:
        ResourcePolicy.check_user_resource_permission(
            session=session,
            username=context.username,
            groups=context.groups,
            resource_uri=datasetUri,
            permission_name=SUMMARY_DATASET,
        )
        dataset = DatasetService.get_dataset_by_uri(session, datasetUri)
        environment = Environment.get_environment_by_uri(
            session, dataset.environmentUri
        )

        pivot_session = SessionHelper.remote_session(dataset.AwsAccountId)
        env_admin_session = SessionHelper.get_session(
            base_session=pivot_session,
            role_arn=environment.EnvironmentDefaultIAMRoleArn,
        )
        s3 = env_admin_session.client('s3', region_name=dataset.region)

        s3.put_object(
            Bucket=environment.EnvironmentDefaultBucketName,
            Key=f'summary/{datasetUri}/summary.md',
            Body=content,
        )
    return True


def get_dataset_stack(context: Context, source: Dataset, **kwargs):
    if not source:
        return None
    return stack_helper.get_stack_with_cfn_resources(
        targetUri=source.datasetUri,
        environmentUri=source.environmentUri,
    )


def get_crawler(context, source, datasetUri: str = None, name: str = None):
    with context.engine.scoped_session() as session:
        ResourcePolicy.check_user_resource_permission(
            session=session,
            username=context.username,
            groups=context.groups,
            resource_uri=datasetUri,
            permission_name=CRAWL_DATASET,
        )
        dataset = DatasetService.get_dataset_by_uri(session, datasetUri)

    aws_session = SessionHelper.remote_session(dataset.AwsAccountId)
    client = aws_session.client('glue', region_name=dataset.region)

    response = client.get_crawler(Name=name)
    return {
        'Name': name,
        'AwsAccountId': dataset.AwsAccountId,
        'region': dataset.region,
        'status': response['Crawler'].get('LastCrawl', {}).get('Status', 'N/A'),
    }


def delete_dataset(
    context: Context, source, datasetUri: str = None, deleteFromAWS: bool = False
):
    with context.engine.scoped_session() as session:
        ResourcePolicy.check_user_resource_permission(
            session=session,
            username=context.username,
            groups=context.groups,
            resource_uri=datasetUri,
            permission_name=DELETE_DATASET,
        )
        dataset: Dataset = DatasetService.get_dataset_by_uri(session, datasetUri)
        env: models.Environment = Environment.get_environment_by_uri(
            session, dataset.environmentUri
        )
        shares = DatasetService.list_dataset_shares_with_existing_shared_items(session, datasetUri)
        if shares:
            raise exceptions.UnauthorizedOperation(
                action=DELETE_DATASET,
                message=f'Dataset {dataset.name} is shared with other teams. '
                'Revoke all dataset shares before deletion.',
            )
        redshift_datasets = DatasetService.list_dataset_redshift_clusters(
            session, datasetUri
        )
        if redshift_datasets:
            raise exceptions.UnauthorizedOperation(
                action=DELETE_DATASET,
                message='Dataset is used by Redshift clusters. '
                'Remove clusters associations first.',
            )

        tables = [t.tableUri for t in DatasetService.get_dataset_tables(session, datasetUri)]
        for uri in tables:
            DatasetIndexer.delete_doc(doc_id=uri)

        folders = [f.locationUri for f in DatasetLocationRepository.get_dataset_folders(session, datasetUri)]
        for uri in folders:
            DatasetIndexer.delete_doc(doc_id=uri)

        DatasetIndexer.delete_doc(doc_id=datasetUri)

        DatasetService.delete_dataset(
            session=session,
            username=context.username,
            groups=context.groups,
            uri=datasetUri,
            data=None,
            check_perm=True,
        )

    if deleteFromAWS:
        stack_helper.delete_stack(
            target_uri=datasetUri,
            accountid=env.AwsAccountId,
            cdk_role_arn=env.CDKRoleArn,
            region=env.region,
        )
        stack_helper.deploy_stack(dataset.environmentUri)
    return True


def get_dataset_glossary_terms(context: Context, source: Dataset, **kwargs):
    if not source:
        return None
    with context.engine.scoped_session() as session:
        terms = (
            session.query(models.GlossaryNode)
            .join(
                models.TermLink, models.TermLink.nodeUri == models.GlossaryNode.nodeUri
            )
            .filter(models.TermLink.targetUri == source.datasetUri)
        )

    return paginate(terms, page_size=100, page=1).to_dict()


def publish_dataset_update(
    context: Context, source, datasetUri: str = None, s3Prefix: str = None
):
    with context.engine.scoped_session() as session:
        ResourcePolicy.check_user_resource_permission(
            session=session,
            username=context.username,
            groups=context.groups,
            resource_uri=datasetUri,
            permission_name=SUBSCRIPTIONS_DATASET,
        )
        dataset = DatasetService.get_dataset_by_uri(session, datasetUri)
        env = db.api.Environment.get_environment_by_uri(session, dataset.environmentUri)
        if not env.subscriptionsEnabled or not env.subscriptionsProducersTopicName:
            raise Exception(
                'Subscriptions are disabled. '
                "First enable subscriptions for this dataset's environment then retry."
            )

        task = models.Task(
            targetUri=datasetUri,
            action='sns.dataset.publish_update',
            payload={'s3Prefix': s3Prefix},
        )
        session.add(task)

    response = Worker.process(
        engine=context.engine, task_ids=[task.taskUri], save_response=False
    )[0]
    log.info(f'Dataset update publish response: {response}')
    return True


def resolve_redshift_copy_enabled(context, source: Dataset, clusterUri: str):
    if not source:
        return None
    with context.engine.scoped_session() as session:
        return db.api.RedshiftCluster.get_cluster_dataset(
            session, clusterUri, source.datasetUri
        ).datasetCopyEnabled


def _deploy_dataset_stack(dataset: Dataset):
    """
    Each dataset stack deployment triggers environment stack update
    to rebuild teams IAM roles data access policies
    """
    stack_helper.deploy_stack(dataset.datasetUri)
    stack_helper.deploy_stack(dataset.environmentUri)


def list_datasets_created_in_environment(
    context: Context, source, environmentUri: str = None, filter: dict = None
):
    if not filter:
        filter = {}
    with context.engine.scoped_session() as session:
        return DatasetService.paginated_environment_datasets(
            session=session,
            uri=environmentUri,
            data=filter,
        )


def list_datasets_owned_by_env_group(
    context, source, environmentUri: str = None, groupUri: str = None, filter: dict = None
):
    if not filter:
        filter = {}
    with context.engine.scoped_session() as session:
        return DatasetService.paginated_environment_group_datasets(
            session=session,
            envUri=environmentUri,
            groupUri=groupUri,
            data=filter,
        )