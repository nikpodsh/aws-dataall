from sqlalchemy import and_

from dataall.db import paginate, models
from dataall.db.exceptions import ObjectNotFound
from dataall.modules.datasets_base.db.models import DatasetProfilingRun, DatasetTable, Dataset


class DatasetProfilingRepository:
    def __init__(self):
        pass

    @staticmethod
    def save_profiling(session, dataset, env, glue_table_name):
        run = DatasetProfilingRun(
            datasetUri=dataset.datasetUri,
            status='RUNNING',
            AwsAccountId=env.AwsAccountId,
            GlueJobName=dataset.GlueProfilingJobName or 'Unknown',
            GlueTriggerSchedule=dataset.GlueProfilingTriggerSchedule,
            GlueTriggerName=dataset.GlueProfilingTriggerName,
            GlueTableName=glue_table_name,
            GlueJobRunId=None,
            owner=dataset.owner,
            label=dataset.GlueProfilingJobName or 'Unknown',
        )

        session.add(run)
        session.commit()
        return run

    @staticmethod
    def update_run(
        session,
        run_uri=None,
        glue_job_run_id=None,
        glue_job_state=None,
        results=None,
    ):
        run = DatasetProfilingRepository.get_profiling_run(
            session, profilingRunUri=run_uri, GlueJobRunId=glue_job_run_id
        )
        if glue_job_run_id:
            run.GlueJobRunId = glue_job_run_id
        if glue_job_state:
            run.status = glue_job_state
        if results:
            run.results = results
        session.commit()
        return run

    @staticmethod
    def get_profiling_run(
        session, profilingRunUri=None, GlueJobRunId=None, GlueTableName=None
    ):
        if profilingRunUri:
            run: DatasetProfilingRun = session.query(
                DatasetProfilingRun
            ).get(profilingRunUri)
        else:
            run: DatasetProfilingRun = (
                session.query(DatasetProfilingRun)
                .filter(DatasetProfilingRun.GlueJobRunId == GlueJobRunId)
                .filter(DatasetProfilingRun.GlueTableName == GlueTableName)
                .first()
            )
        return run

    @staticmethod
    def list_profiling_runs(session, dataset_uri):
        # TODO filter is always default
        filter = {}
        q = (
            session.query(DatasetProfilingRun)
            .filter(DatasetProfilingRun.datasetUri == dataset_uri)
            .order_by(DatasetProfilingRun.created.desc())
        )
        return paginate(
            q, page=filter.get('page', 1), page_size=filter.get('pageSize', 20)
        ).to_dict()

    @staticmethod
    def list_table_profiling_runs(session, table_uri):
        # TODO filter is always default
        filter = {}
        q = (
            session.query(DatasetProfilingRun)
            .join(
                DatasetTable,
                DatasetTable.datasetUri == DatasetProfilingRun.datasetUri,
            )
            .filter(
                and_(
                    DatasetTable.tableUri == table_uri,
                    DatasetTable.GlueTableName == DatasetProfilingRun.GlueTableName,
                )
            )
            .order_by(DatasetProfilingRun.created.desc())
            .all()
        )
        return paginate(
            q, page=filter.get('page', 1), page_size=filter.get('pageSize', 20)
        ).to_dict()

    @staticmethod
    def get_table_last_profiling_run(session, table_uri):
        return (
            session.query(DatasetProfilingRun)
            .join(
                DatasetTable,
                DatasetTable.datasetUri == DatasetProfilingRun.datasetUri,
            )
            .filter(DatasetTable.tableUri == table_uri)
            .filter(
                DatasetTable.GlueTableName
                == DatasetProfilingRun.GlueTableName
            )
            .order_by(DatasetProfilingRun.created.desc())
            .first()
        )

    @staticmethod
    def get_table_last_profiling_run_with_results(session, table_uri):
        return (
            session.query(DatasetProfilingRun)
            .join(
                DatasetTable,
                DatasetTable.datasetUri == DatasetProfilingRun.datasetUri,
            )
            .filter(DatasetTable.tableUri == table_uri)
            .filter(
                DatasetTable.GlueTableName
                == DatasetProfilingRun.GlueTableName
            )
            .filter(DatasetProfilingRun.results.isnot(None))
            .order_by(DatasetProfilingRun.created.desc())
            .first()
        )
