from dataall.modules.notebooks.gql.enums import SagemakerNotebookRole

from dataall import db
from dataall.api.context import Context
from dataall.aws.handlers.sagemaker import Sagemaker
from dataall.db import models, permissions
from dataall.db.api import KeyValueTag, ResourcePolicy, Stack
from dataall.api.Objects.Stack import stack_helper
from dataall.modules.notebooks.services import Notebook


def create_notebook(context: Context, source, input: dict = None):
    """Creates a SageMaker notebook. Deploys the notebooks stack into AWS"""
    with context.engine.scoped_session() as session:

        notebook = Notebook.create_notebook(
            session=session,
            username=context.username,
            groups=context.groups,
            uri=input['environmentUri'],
            data=input,
            check_perm=True,
        )

        Stack.create_stack(
            session=session,
            environment_uri=notebook.environmentUri,
            target_type='notebook',
            target_uri=notebook.notebookUri,
            target_label=notebook.label,
        )

    stack_helper.deploy_stack(context=context, targetUri=notebook.notebookUri)

    return notebook


def list_notebooks(context, source, filter: dict = None):
    """
    Lists all SageMaker notebooks using the given filter.
    If the filter is not provided, all notebooks are returned.
    """

    if not filter:
        filter = {}
    with context.engine.scoped_session() as session:
        return Notebook.paginated_user_notebooks(
            session=session,
            username=context.username,
            groups=context.groups,
            uri=None,
            data=filter,
            check_perm=True,
        )


def get_notebook(context, source, notebookUri: str = None):
    """Retrieve a SageMaker notebook by URI."""
    with context.engine.scoped_session() as session:
        return Notebook.get_notebook(
            session=session,
            username=context.username,
            groups=context.groups,
            uri=notebookUri,
            data=None,
            check_perm=True,
        )


def resolve_notebook_status(context, source: models.SagemakerNotebook, **kwargs):
    """Resolves the status of a notebook."""
    if not source:
        return None
    return Sagemaker.get_notebook_instance_status(
        AwsAccountId=source.AWSAccountId,
        region=source.region,
        NotebookInstanceName=source.NotebookInstanceName,
    )


def start_notebook(context, source: models.SagemakerNotebook, notebookUri: str = None):
    """Starts a sagemaker notebook instance"""
    with context.engine.scoped_session() as session:
        ResourcePolicy.check_user_resource_permission(
            session=session,
            username=context.username,
            groups=context.groups,
            resource_uri=notebookUri,
            permission_name=permissions.UPDATE_NOTEBOOK,
        )
        notebook = Notebook.get_notebook(
            session=session,
            username=context.username,
            groups=context.groups,
            uri=notebookUri,
            data=None,
            check_perm=True,
        )
        Sagemaker.start_instance(
            notebook.AWSAccountId, notebook.region, notebook.NotebookInstanceName
        )
    return 'Starting'


def stop_notebook(context, source: models.SagemakerNotebook, notebookUri: str = None):
    """Stops a notebook instance."""
    with context.engine.scoped_session() as session:
        ResourcePolicy.check_user_resource_permission(
            session=session,
            username=context.username,
            groups=context.groups,
            resource_uri=notebookUri,
            permission_name=permissions.UPDATE_NOTEBOOK,
        )
        notebook = Notebook.get_notebook(
            session=session,
            username=context.username,
            groups=context.groups,
            uri=notebookUri,
            data=None,
            check_perm=True,
        )
        Sagemaker.stop_instance(
            notebook.AWSAccountId, notebook.region, notebook.NotebookInstanceName
        )
    return 'Stopping'


def get_notebook_presigned_url(
    context, source: models.SagemakerNotebook, notebookUri: str = None
):
    """Creates and returns a presigned url for a notebook"""
    with context.engine.scoped_session() as session:
        ResourcePolicy.check_user_resource_permission(
            session=session,
            username=context.username,
            groups=context.groups,
            resource_uri=notebookUri,
            permission_name=permissions.GET_NOTEBOOK,
        )
        notebook = Notebook.get_notebook(
            session=session,
            username=context.username,
            groups=context.groups,
            uri=notebookUri,
            data=None,
            check_perm=True,
        )
        url = Sagemaker.presigned_url(
            notebook.AWSAccountId, notebook.region, notebook.NotebookInstanceName
        )
        return url


def delete_notebook(
    context,
    source: models.SagemakerNotebook,
    notebookUri: str = None,
    deleteFromAWS: bool = None,
):
    """
    Deletes the SageMaker notebook.
    Deletes the notebooks stack from AWS if deleteFromAWS is True
    """
    
    with context.engine.scoped_session() as session:
        ResourcePolicy.check_user_resource_permission(
            session=session,
            resource_uri=notebookUri,
            permission_name=permissions.DELETE_NOTEBOOK,
            groups=context.groups,
            username=context.username,
        )
        notebook = Notebook.get_notebook_by_uri(session, notebookUri)
        env: models.Environment = db.api.Environment.get_environment_by_uri(
            session, notebook.environmentUri
        )

        KeyValueTag.delete_key_value_tags(session, notebook.notebookUri, 'notebook')

        session.delete(notebook)

        ResourcePolicy.delete_resource_policy(
            session=session,
            resource_uri=notebook.notebookUri,
            group=notebook.SamlAdminGroupName,
        )

    if deleteFromAWS:
        stack_helper.delete_stack(
            context=context,
            target_uri=notebookUri,
            accountid=env.AwsAccountId,
            cdk_role_arn=env.CDKRoleArn,
            region=env.region,
            target_type='notebook',
        )

    return True

#TODO: check for the code duplication
def resolve_environment(context, source, **kwargs):
    if not source:
        return None
    with context.engine.scoped_session() as session:
        return session.query(models.Environment).get(source.environmentUri)


def resolve_organization(context, source, **kwargs):
    if not source:
        return None
    with context.engine.scoped_session() as session:
        env: models.Environment = session.query(models.Environment).get(
            source.environmentUri
        )
        return session.query(models.Organization).get(env.organizationUri)


def resolve_user_role(context: Context, source: models.SagemakerNotebook):
    if not source:
        return None
    if source.owner == context.username:
        return SagemakerNotebookRole.CREATOR.value
    elif context.groups and source.SamlAdminGroupName in context.groups:
        return SagemakerNotebookRole.ADMIN.value
    return SagemakerNotebookRole.NO_PERMISSION.value


def resolve_stack(context: Context, source: models.SagemakerNotebook, **kwargs):
    if not source:
        return None
    return stack_helper.get_stack_with_cfn_resources(
        context=context,
        targetUri=source.notebookUri,
        environmentUri=source.environmentUri,
    )
