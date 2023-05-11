"""Indexes Datasets in OpenSearch"""

from dataall.db import models
from dataall.db.api import Vote
from dataall.modules.datasets_base.db.dataset_repository import DatasetRepository
from dataall.modules.datasets_base.db.models import Dataset
from dataall.modules.datasets.db.dataset_location_repository import DatasetLocationRepository
from dataall.searchproxy.base_indexer import BaseIndexer


class DatasetIndexer(BaseIndexer):

    @classmethod
    def upsert(cls, session, dataset_uri: str):
        dataset = (
            session.query(
                Dataset.datasetUri.label('datasetUri'),
                Dataset.name.label('name'),
                Dataset.owner.label('owner'),
                Dataset.label.label('label'),
                Dataset.description.label('description'),
                Dataset.confidentiality.label('classification'),
                Dataset.tags.label('tags'),
                Dataset.topics.label('topics'),
                Dataset.region.label('region'),
                models.Organization.organizationUri.label('orgUri'),
                models.Organization.name.label('orgName'),
                models.Environment.environmentUri.label('envUri'),
                models.Environment.name.label('envName'),
                Dataset.SamlAdminGroupName.label('admins'),
                Dataset.GlueDatabaseName.label('database'),
                Dataset.S3BucketName.label('source'),
                Dataset.created,
                Dataset.updated,
                Dataset.deleted,
            )
            .join(
                models.Organization,
                Dataset.organizationUri == models.Organization.organizationUri,
            )
            .join(
                models.Environment,
                Dataset.environmentUri == models.Environment.environmentUri,
            )
            .filter(Dataset.datasetUri == dataset_uri)
            .first()
        )
        count_tables = DatasetRepository.count_dataset_tables(session, dataset_uri)
        count_folders = DatasetLocationRepository.count_dataset_locations(session, dataset_uri)
        count_upvotes = Vote.count_upvotes(
            session, None, None, dataset_uri, {'targetType': 'dataset'}
        )

        if dataset:
            glossary = BaseIndexer._get_target_glossary_terms(session, dataset_uri)
            BaseIndexer._index(
                doc_id=dataset_uri,
                doc={
                    'name': dataset.name,
                    'owner': dataset.owner,
                    'label': dataset.label,
                    'admins': dataset.admins,
                    'database': dataset.database,
                    'source': dataset.source,
                    'resourceKind': 'dataset',
                    'description': dataset.description,
                    'classification': dataset.classification,
                    'tags': [t.replace('-', '') for t in dataset.tags or []],
                    'topics': dataset.topics,
                    'region': dataset.region.replace('-', ''),
                    'environmentUri': dataset.envUri,
                    'environmentName': dataset.envName,
                    'organizationUri': dataset.orgUri,
                    'organizationName': dataset.orgName,
                    'created': dataset.created,
                    'updated': dataset.updated,
                    'deleted': dataset.deleted,
                    'glossary': glossary,
                    'tables': count_tables,
                    'folders': count_folders,
                    'upvotes': count_upvotes,
                },
            )
        return dataset
