import logging
from typing import List

from aws_cdk import aws_iam

from ....db import permissions

logger = logging.getLogger()


class ServicePolicy(object):
    def __init__(
        self,
        stack,
        id,
        name,
        account,
        region,
        role_name,
        tag_key,
        tag_value,
        resource_prefix,
        permissions,
    ):
        self.stack = stack
        self.id = id
        self.name = name
        self.account = account
        self.region = region
        self.tag_key = tag_key
        self.tag_value = tag_value
        self.resource_prefix = resource_prefix
        self.permissions = permissions
        self.role_name = role_name

    def generate_policies(self) -> [aws_iam.ManagedPolicy]:
        """
        Creates aws_iam.Policy based on declared subclasses of Policy object
        """
        policies: [aws_iam.ManagedPolicy] = [
            # This policy covers the minumum actions required independent
            # of the service permissions given to the group.
            # The 'glue:GetTable', 'glue:GetPartitions' and
            # 'lakeformation:GetDataAccess' actions are additionally
            # required for the Worksheet/Athena feature.
            aws_iam.ManagedPolicy(
                self.stack,
                self.id,
                managed_policy_name=f'{self.id}-0',
                statements=[
                    aws_iam.PolicyStatement(
                        actions=[
                            'athena:ListEngineVersions',
                            'athena:ListDataCatalogs',
                            'athena:ListWorkGroups',
                            'glue:GetTable',
                            'glue:GetPartitions',
                            'lakeformation:GetDataAccess',
                            'kms:Decrypt',
                            'kms:DescribeKey',
                            'kms:Encrypt',
                            'kms:ReEncrypt*',
                            'kms:GenerateDataKey*',
                            'secretsmanager:GetSecretValue',
                            'secretsmanager:DescribeSecret',
                            'secretsmanager:ListSecrets',
                            'ssm:GetParametersByPath',
                            'ssm:GetParameters',
                            'ssm:GetParameter',
                            'ec2:Describe*',
                            'logs:Describe*',
                            'logs:Get*',
                            'logs:List*',
                            'iam:list*',
                            'iam:Get*',
                            'tag:GetResources',
                            'tag:TagResources',
                            'tag:UntagResources',
                            'tag:GetTagValues',
                            'tag:GetTagKeys',
                        ],
                        resources=['*'],
                    ),
                    aws_iam.PolicyStatement(
                        actions=[
                            'iam:PassRole',
                        ],
                        resources=[
                            f'arn:aws:iam::{self.account}:role/{self.role_name}'
                        ],
                    ),
                ],
            )
        ]

        services = ServicePolicy.__subclasses__()

        statements = []
        for service in services:
            statements.extend(service.get_statements(self, self.permissions))

        statements_chunks: list = [
            statements[i : i + 8] for i in range(0, len(statements), 8)
        ]

        for index, chunk in enumerate(statements_chunks):
            policies.append(
                aws_iam.ManagedPolicy(
                    self.stack,
                    f'{self.id}-{index+1}',
                    managed_policy_name=f'{self.id}-{index+1}',
                    statements=chunk,
                )
            )
        return policies

    def get_statements(self, group_permissions, **kwargs) -> List[aws_iam.PolicyStatement]:
        """
        This method implements a policy based on a tag key and optionally a resource prefix
        :return: list
        """
        raise NotImplementedError(
            'Policy subclasses need to implement the get_statements class method'
        )
