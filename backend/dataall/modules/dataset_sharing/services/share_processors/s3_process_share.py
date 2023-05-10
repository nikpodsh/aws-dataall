import logging

from dataall.db import models
from ..share_managers import S3ShareManager
from dataall.modules.datasets_base.db.models import DatasetStorageLocation, Dataset
from dataall.modules.dataset_sharing.db.enums import ShareItemStatus, ShareObjectActions, ShareItemActions
from dataall.modules.dataset_sharing.db.models import ShareObject
from dataall.modules.dataset_sharing.services.share_object import ShareObjectService, ShareItemSM

log = logging.getLogger(__name__)


class ProcessS3Share(S3ShareManager):
    def __init__(
        self,
        session,
        dataset: Dataset,
        share: ShareObject,
        share_folder: DatasetStorageLocation,
        source_environment: models.Environment,
        target_environment: models.Environment,
        source_env_group: models.EnvironmentGroup,
        env_group: models.EnvironmentGroup,
    ):

        super().__init__(
            session,
            dataset,
            share,
            share_folder,
            source_environment,
            target_environment,
            source_env_group,
            env_group,
        )

    @classmethod
    def process_approved_shares(
        cls,
        session,
        dataset: Dataset,
        share: ShareObject,
        share_folders: [DatasetStorageLocation],
        source_environment: models.Environment,
        target_environment: models.Environment,
        source_env_group: models.EnvironmentGroup,
        env_group: models.EnvironmentGroup
    ) -> bool:
        """
        1) update_share_item_status with Start action
        2) (one time only) manage_bucket_policy - grants permission in the bucket policy
        3) grant_target_role_access_policy
        4) manage_access_point_and_policy
        5) update_dataset_bucket_key_policy
        6) update_share_item_status with Finish action

        Returns
        -------
        True if share is granted successfully
        """
        log.info(
            '##### Starting Sharing folders #######'
        )
        success = True
        for folder in share_folders:
            log.info(f'sharing folder: {folder}')
            sharing_item = ShareObjectService.find_share_item_by_folder(
                session,
                share,
                folder,
            )
            shared_item_SM = ShareItemSM(ShareItemStatus.Share_Approved.value)
            new_state = shared_item_SM.run_transition(ShareObjectActions.Start.value)
            shared_item_SM.update_state_single_item(session, sharing_item, new_state)

            sharing_folder = cls(
                session,
                dataset,
                share,
                folder,
                source_environment,
                target_environment,
                source_env_group,
                env_group,
            )

            try:
                sharing_folder.manage_bucket_policy()
                sharing_folder.grant_target_role_access_policy()
                sharing_folder.manage_access_point_and_policy()
                sharing_folder.update_dataset_bucket_key_policy()

                new_state = shared_item_SM.run_transition(ShareItemActions.Success.value)
                shared_item_SM.update_state_single_item(session, sharing_item, new_state)

            except Exception as e:
                sharing_folder.handle_share_failure(e)
                new_state = shared_item_SM.run_transition(ShareItemActions.Failure.value)
                shared_item_SM.update_state_single_item(session, sharing_item, new_state)
                success = False

        return success

    @classmethod
    def process_revoked_shares(
            cls,
            session,
            dataset: Dataset,
            share: ShareObject,
            revoke_folders: [DatasetStorageLocation],
            source_environment: models.Environment,
            target_environment: models.Environment,
            source_env_group: models.EnvironmentGroup,
            env_group: models.EnvironmentGroup
    ) -> bool:
        """
        1) update_share_item_status with Start action
        2) delete_access_point_policy for folder
        3) update_share_item_status with Finish action

        Returns
        -------
        True if share is revoked successfully
        """

        log.info(
            '##### Starting Revoking folders #######'
        )
        success = True
        for folder in revoke_folders:
            log.info(f'revoking access to folder: {folder}')
            removing_item = ShareObjectService.find_share_item_by_folder(
                session,
                share,
                folder,
            )

            revoked_item_SM = ShareItemSM(ShareItemStatus.Revoke_Approved.value)
            new_state = revoked_item_SM.run_transition(ShareObjectActions.Start.value)
            revoked_item_SM.update_state_single_item(session, removing_item, new_state)

            removing_folder = cls(
                session,
                dataset,
                share,
                folder,
                source_environment,
                target_environment,
                source_env_group,
                env_group,
            )

            try:
                removing_folder.delete_access_point_policy()

                new_state = revoked_item_SM.run_transition(ShareItemActions.Success.value)
                revoked_item_SM.update_state_single_item(session, removing_item, new_state)

            except Exception as e:
                removing_folder.handle_revoke_failure(e)
                new_state = revoked_item_SM.run_transition(ShareItemActions.Failure.value)
                revoked_item_SM.update_state_single_item(session, removing_item, new_state)
                success = False

        return success

    @staticmethod
    def clean_up_share(
            dataset: Dataset,
            share: ShareObject,
            target_environment: models.Environment
    ):
        """
        1) deletes S3 access point for this share in this Dataset S3 Bucket
        2) delete_target_role_access_policy to access the above deleted access point
        3) delete_dataset_bucket_key_policy to remove access to the requester IAM role

        Returns
        -------
        True if share is cleaned-up successfully
        """

        clean_up = S3ShareManager.delete_access_point(
            share=share,
            dataset=dataset
        )
        if clean_up:
            S3ShareManager.delete_target_role_access_policy(
                share=share,
                dataset=dataset,
                target_environment=target_environment
            )
            S3ShareManager.delete_dataset_bucket_key_policy(
                share=share,
                dataset=dataset,
                target_environment=target_environment
            )

        return True
