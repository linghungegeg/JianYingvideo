"""add cdk templates

Revision ID: f1a2b3c4d5e6
Revises: 7b9c4d1e2f30
Create Date: 2026-03-23 10:35:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'f1a2b3c4d5e6'
down_revision = '7b9c4d1e2f30'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table('cdk_templates'):
        return
    op.create_table(
        'cdk_templates',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('duration_days', sa.Integer(), nullable=False, server_default='30'),
        sa.Column('bonus_points', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('device_limit', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('transfer_times', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('redeem_days', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('name', name='uq_cdk_templates_name'),
    )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table('cdk_templates'):
        return
    op.drop_table('cdk_templates')
