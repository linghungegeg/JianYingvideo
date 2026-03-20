"""add metadata to user_materials

Revision ID: b1c2d3e4f5g6
Revises: a1b2c3d4e5f6
Create Date: 2026-03-16 18:10:00

"""
from alembic import op
import sqlalchemy as sa

revision = 'b1c2d3e4f5g6'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user_materials', schema=None) as batch_op:
        batch_op.add_column(sa.Column('metadata', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('user_materials', schema=None) as batch_op:
        batch_op.drop_column('metadata')
