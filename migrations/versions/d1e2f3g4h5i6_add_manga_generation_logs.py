"""add manga_generation_logs

Revision ID: d1e2f3g4h5i6
Revises: c1d2e3f4g5h6
Create Date: 2026-03-16 19:20:00

"""
from alembic import op
import sqlalchemy as sa

revision = 'd1e2f3g4h5i6'
down_revision = 'c1d2e3f4g5h6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'manga_generation_logs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('project_id', sa.String(length=64), nullable=False),
        sa.Column('project_name', sa.String(length=200), nullable=True),
        sa.Column('params_json', sa.Text(), nullable=False),
        sa.Column('first_material_id', sa.Integer(), sa.ForeignKey('user_materials.id'), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=True),
        sa.Column('error_msg', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_table('manga_generation_logs')
