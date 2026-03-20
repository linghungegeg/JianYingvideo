"""add ai byok tables

Revision ID: 2c3f7f0a8f5b
Revises: f94b656ac4fb
Create Date: 2026-03-16 14:20:00

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '2c3f7f0a8f5b'
down_revision = 'f94b656ac4fb'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'ai_providers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('provider_code', sa.String(length=50), nullable=False),
        sa.Column('provider_name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('logo_url', sa.String(length=500), nullable=True),
        sa.Column('docs_url', sa.String(length=500), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True, server_default=sa.text('1')),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('provider_code')
    )

    op.create_table(
        'user_api_keys',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('provider_id', sa.Integer(), nullable=False),
        sa.Column('key_name', sa.String(length=100), nullable=False),
        sa.Column('api_key', sa.Text(), nullable=False),
        sa.Column('api_secret', sa.Text(), nullable=True),
        sa.Column('endpoint', sa.String(length=500), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True, server_default=sa.text('1')),
        sa.Column('last_used_at', sa.DateTime(), nullable=True),
        sa.Column('usage_count', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['provider_id'], ['ai_providers.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table(
        'ai_generation_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('key_id', sa.Integer(), nullable=True),
        sa.Column('provider_code', sa.String(length=50), nullable=False),
        sa.Column('task_type', sa.String(length=50), nullable=False),
        sa.Column('prompt', sa.Text(), nullable=True),
        sa.Column('result_path', sa.String(length=500), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True, server_default='success'),
        sa.Column('error_msg', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['key_id'], ['user_api_keys.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    providers = sa.table(
        'ai_providers',
        sa.column('provider_code', sa.String),
        sa.column('provider_name', sa.String),
        sa.column('description', sa.Text),
        sa.column('logo_url', sa.String),
        sa.column('docs_url', sa.String),
        sa.column('is_active', sa.Boolean),
    )
    op.bulk_insert(providers, [
        {
            'provider_code': 'jimeng',
            'provider_name': '即梦AI',
            'description': '图像/视频生成与创意内容',
            'logo_url': '',
            'docs_url': '',
            'is_active': True,
        },
        {
            'provider_code': 'volc',
            'provider_name': '火山引擎',
            'description': '语音合成 TTS 等能力',
            'logo_url': '',
            'docs_url': '',
            'is_active': True,
        },
        {
            'provider_code': 'openai',
            'provider_name': 'OpenAI',
            'description': '文本/图片/音频生成',
            'logo_url': '',
            'docs_url': '',
            'is_active': True,
        },
    ])


def downgrade():
    op.drop_table('ai_generation_logs')
    op.drop_table('user_api_keys')
    op.drop_table('ai_providers')
