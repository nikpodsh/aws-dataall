import logging

from dataall.modules.datasets.indexers.location_indexer import DatasetLocationIndexer
from dataall.modules.datasets.indexers.table_indexer import DatasetTableIndexer
from dataall.modules.datasets_base.db.dataset_repository import DatasetRepository
from dataall.modules.datasets_base.db.models import Dataset
from dataall.tasks.catalog_indexer import CatalogIndexer

log = logging.getLogger(__name__)


class DatasetCatalogIndexer(CatalogIndexer):

    def index(self, session) -> int:
        all_datasets: [Dataset] = DatasetRepository.list_all_active_datasets(session)
        log.info(f'Found {len(all_datasets)} datasets')
        dataset: Dataset
        for dataset in all_datasets:
            tables = DatasetTableIndexer.upsert_all(session, dataset.datasetUri)
            folders = DatasetLocationIndexer.upsert_all(session, dataset_uri=dataset.datasetUri)
            return len(tables) + len(folders) + 1