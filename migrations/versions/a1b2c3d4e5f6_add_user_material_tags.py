"""add tags to user_materials

Revision ID: a1b2c3d4e5f6
Revises: 9c1a2b3c4d5e
Create Date: 2026-03-16 17:30:00

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '9c1a2b3c4d5e'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user_materials', schema=None) as batch_op:
        batch_op.add_column(sa.Column('tags', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('user_materials', schema=None) as batch_op:
        batch_op.drop_column('tags')
