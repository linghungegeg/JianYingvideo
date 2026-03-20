"""add user_quota_logs

Revision ID: e1f2g3h4i5j6
Revises: d1e2f3g4h5i6
Create Date: 2026-03-16 19:55:00

"""
from alembic import op
import sqlalchemy as sa

revision = 'e1f2g3h4i5j6'
down_revision = 'd1e2f3g4h5i6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'user_quota_logs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('change', sa.Integer(), nullable=False),
        sa.Column('reason', sa.String(length=100), nullable=False),
        sa.Column('project_id', sa.String(length=64), nullable=True),
        sa.Column('remaining_after', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_table('user_quota_logs')
