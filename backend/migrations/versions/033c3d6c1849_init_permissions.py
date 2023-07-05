"""init permissions

Revision ID: 033c3d6c1849
Revises: bc77fef9d0b2
Create Date: 2021-08-03 07:53:28.164238

"""
import os

from alembic import op
import sqlalchemy as sa
from sqlalchemy import orm

from dataall.db import api, get_engine, has_table

# revision identifiers, used by Alembic.
revision = '033c3d6c1849'
down_revision = 'bc77fef9d0b2'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    try:
        bind = op.get_bind()
        session = orm.Session(bind=bind)
        print('Initializing permissions...')
        Permission.init_permissions(session)
        print('Permissions initialized successfully')
    except Exception as e:
        print(f'Failed to init permissions due to: {e}')
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    pass
    # ### end Alembic commands ###
