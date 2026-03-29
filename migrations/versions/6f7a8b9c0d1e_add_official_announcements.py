"""add official announcements

Revision ID: 6f7a8b9c0d1e
Revises: f2a3b4c5d6e7
Create Date: 2026-03-29 16:20:00

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "6f7a8b9c0d1e"
down_revision = "f2a3b4c5d6e7"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if inspector.has_table("official_announcements"):
        return
    op.create_table(
        "official_announcements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table("official_announcements"):
        return
    op.drop_table("official_announcements")
