"""add base_url to user_api_keys

Revision ID: 4a9b2c7d1e6f
Revises: 3b4b6f0b1d2c
Create Date: 2026-03-16 16:25:00

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '4a9b2c7d1e6f'
down_revision = '3b4b6f0b1d2c'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user_api_keys', schema=None) as batch_op:
        batch_op.add_column(sa.Column('base_url', sa.String(length=500), nullable=True))


def downgrade():
    with op.batch_alter_table('user_api_keys', schema=None) as batch_op:
        batch_op.drop_column('base_url')
