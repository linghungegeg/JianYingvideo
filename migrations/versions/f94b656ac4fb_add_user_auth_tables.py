"""add user auth tables

Revision ID: f94b656ac4fb
Revises: 72809966927e
Create Date: 2026-03-15 18:21:23.094488

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = 'f94b656ac4fb'
down_revision = '72809966927e'
branch_labels = None
depends_on = None


def upgrade():
    # users table additions
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('email', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('updated_at', sa.DateTime(), nullable=True))
        batch_op.alter_column('password_hash',
               existing_type=mysql.VARCHAR(collation='utf8mb4_unicode_ci', length=128),
               type_=sa.String(length=256),
               existing_nullable=False)
        batch_op.create_unique_constraint('uq_users_email', ['email'])

    # user_quota
    op.create_table('user_quota',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('total_generated', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('remaining', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('vip_expire_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('user_id')
    )

    # user_tokens
    op.create_table('user_tokens',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('token', sa.String(length=128), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('user_tokens', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_user_tokens_token'), ['token'], unique=True)


def downgrade():
    with op.batch_alter_table('user_tokens', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_user_tokens_token'))

    op.drop_table('user_tokens')
    op.drop_table('user_quota')

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_constraint('uq_users_email', type_='unique')
        batch_op.alter_column('password_hash',
               existing_type=sa.String(length=256),
               type_=mysql.VARCHAR(collation='utf8mb4_unicode_ci', length=128),
               existing_nullable=False)
        batch_op.drop_column('updated_at')
        batch_op.drop_column('email')
