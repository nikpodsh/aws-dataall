import logging
from typing import List

from aws_cdk import aws_iam as iam

from ....db import models

logger = logging.getLogger()


class DataPolicy:
    def __init__(
        self,
        stack,
        id,
        name,
        account,
        region,
        tag_key,
        tag_value,
        resource_prefix,
        environment: models.Environment,
        team: models.EnvironmentGroup,
    ):
        self.stack = stack
        self.id = id
        self.name = name
        self.account = account
        self.region = region
        self.tag_key = tag_key
        self.tag_value = tag_value
        self.resource_prefix = resource_prefix
        self.environment = environment
        self.team = team

    def generate_admins_data_access_policy(self) -> iam.Policy:
        """
        Creates an open ws_iam.Policy for environment admins
        """

        policy: iam.Policy = iam.Policy(
            self.stack,
            self.id,
            policy_name=self.name,
            statements=[
                iam.PolicyStatement(
                    actions=[
                        's3:List*',
                        's3:Get*',
                        's3:PutAccountPublicAccessBlock',
                        's3:PutAccessPointPublicAccessBlock',
                        's3:PutStorageLensConfiguration',
                        's3:GetAccessPoint',
                        's3:GetAccessPointPolicy',
                        's3:ListAccessPoints',
                        's3:CreateAccessPoint',
                        's3:DeleteAccessPoint',
                        's3:GetAccessPointPolicyStatus',
                        's3:DeleteAccessPointPolicy',
                        's3:PutAccessPointPolicy',
                        's3:CreateJob',
                    ],
                    resources=['*'],
                ),
                iam.PolicyStatement(
                    actions=['s3:*'],
                    resources=[
                        f'arn:aws:s3-object-lambda:{self.region}:{self.account}:accesspoint/*',
                        f'arn:aws:s3:{self.region}:{self.account}:job/*',
                        f'arn:aws:s3:{self.region}:{self.account}:storage-lens/*',
                        f'arn:aws:s3:us-west-2:{self.account}:async-request/mrap/*/*',
                        f'arn:aws:s3:{self.region}:{self.account}:accesspoint/*',
                        f'arn:aws:s3:::{self.resource_prefix}*/*',
                        f'arn:aws:s3:::{self.resource_prefix}*',
                    ],
                ),
                iam.PolicyStatement(
                    actions=['athena:*', 'lakeformation:*', 'glue:*', 'kms:*'],
                    resources=['*'],
                ),
            ],
        )
        logger.debug(f'Final generated policy {policy.document.to_json()}')

        return policy

    def generate_data_access_policy(self, session) -> iam.Policy:
        """
        Creates aws_iam.Policy based on team datasets
        """
        statements: List[iam.PolicyStatement] = self.get_statements(session)

        for extension in DataPolicy.__subclasses__():
            statements.extend(extension.get_statements(self, session=session))

        policy: iam.Policy = iam.Policy(
            self.stack,
            self.id,
            policy_name=self.name,
            statements=statements,
        )
        logger.debug(f'Final generated policy {policy.document.to_json()}')

        return policy

    def get_statements(self, *args, **kwargs):
        statements = [
            iam.PolicyStatement(
                actions=[
                    's3:List*',
                    's3:Get*',
                    's3:PutAccountPublicAccessBlock',
                    's3:PutAccessPointPublicAccessBlock',
                    's3:PutStorageLensConfiguration',
                    's3:CreateJob',
                    's3:GetAccessPoint',
                    's3:GetAccessPointPolicy',
                    's3:ListAccessPoints',
                    's3:CreateAccessPoint',
                    's3:DeleteAccessPoint',
                    's3:GetAccessPointPolicyStatus',
                    's3:DeleteAccessPointPolicy',
                    's3:PutAccessPointPolicy',
                ],
                resources=['*'],
            ),
            iam.PolicyStatement(
                actions=['s3:*'],
                resources=[
                    f'arn:aws:s3-object-lambda:{self.region}:{self.account}:accesspoint/*',
                    f'arn:aws:s3:{self.region}:{self.account}:job/*',
                    f'arn:aws:s3:{self.region}:{self.account}:storage-lens/*',
                    f'arn:aws:s3:us-west-2:{self.account}:async-request/mrap/*/*',
                    f'arn:aws:s3:{self.region}:{self.account}:accesspoint/*',
                ],
            ),
        ]

        self.set_allowed_s3_buckets_statements(statements)

        self.set_athena_statements(statements)

        return statements

    def set_allowed_s3_buckets_statements(self, statements):
        allowed_buckets = [
            f'arn:aws:s3:::{self.environment.EnvironmentDefaultBucketName}',
            f'arn:aws:s3:::{self.environment.EnvironmentDefaultBucketName}/*',
        ]
        statements.extend(
            [
                iam.PolicyStatement(
                    actions=['s3:*'],
                    resources=allowed_buckets,
                )
            ]
        )

    def set_athena_statements(self, statements):
        statements.extend(
            [
                iam.PolicyStatement(
                    actions=['athena:*'],
                    resources=[
                        f'arn:aws:athena:{self.region}:{self.account}:workgroup/{self.team.environmentAthenaWorkGroup}',
                        f'arn:aws:athena:{self.region}:{self.account}:datacatalog/*',
                    ],
                )
            ]
        )
