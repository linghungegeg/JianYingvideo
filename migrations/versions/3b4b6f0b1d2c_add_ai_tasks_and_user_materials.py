"""add ai tasks and user materials

Revision ID: 3b4b6f0b1d2c
Revises: 2c3f7f0a8f5b
Create Date: 2026-03-16 15:10:00

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '3b4b6f0b1d2c'
down_revision = '2c3f7f0a8f5b'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'ai_tasks',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('key_id', sa.Integer(), nullable=True),
        sa.Column('provider_code', sa.String(length=50), nullable=False),
        sa.Column('task_type', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=True, server_default='pending'),
        sa.Column('prompt', sa.Text(), nullable=True),
        sa.Column('result_path', sa.String(length=500), nullable=True),
        sa.Column('result_text', sa.Text(), nullable=True),
        sa.Column('error_msg', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['key_id'], ['user_api_keys.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table(
        'user_materials',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('file_path', sa.String(length=500), nullable=False),
        sa.Column('file_type', sa.String(length=50), nullable=False),
        sa.Column('source', sa.String(length=50), nullable=True, server_default='ai'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('user_materials')
    op.drop_table('ai_tasks')
