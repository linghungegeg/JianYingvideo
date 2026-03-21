"""add resource exchange posts table

Revision ID: 7b9c4d1e2f30
Revises: 26b0740509b7
Create Date: 2026-03-21 18:45:00
"""

from __future__ import annotations

import json
from datetime import datetime

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "7b9c4d1e2f30"
down_revision = "26b0740509b7"
branch_labels = None
depends_on = None

_RESOURCE_EXCHANGE_CONFIG_KEY = "resource_exchange_posts_v1"


def _parse_iso_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if not inspector.has_table("resource_exchange_posts"):
        op.create_table(
            "resource_exchange_posts",
            sa.Column("id", sa.String(length=32), primary_key=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("username", sa.String(length=80), nullable=False),
            sa.Column("membership_label", sa.String(length=32), nullable=False, server_default="试用用户"),
            sa.Column("membership_value", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("project_name", sa.String(length=64), nullable=False),
            sa.Column("project_intro", sa.String(length=255), nullable=False),
            sa.Column("contact", sa.String(length=120), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(), nullable=True),
            sa.Column("approved_at", sa.DateTime(), nullable=True),
            sa.Column("review_reason", sa.String(length=255), nullable=True),
            sa.Column("reviewer_id", sa.Integer(), nullable=True),
            sa.Column("reviewer_name", sa.String(length=80), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"]),
        )
        op.create_index("ix_resource_exchange_posts_user_id", "resource_exchange_posts", ["user_id"])
        op.create_index("ix_resource_exchange_posts_status", "resource_exchange_posts", ["status"])
        op.create_index("ix_resource_exchange_posts_created_at", "resource_exchange_posts", ["created_at"])

    config_rows = []
    if inspector.has_table("config"):
        config_rows = bind.execute(
            sa.text("SELECT value FROM config WHERE `key` = :config_key"),
            {"config_key": _RESOURCE_EXCHANGE_CONFIG_KEY},
        ).fetchall()

    if not config_rows:
        return

    raw_value = config_rows[0][0]
    try:
        items = json.loads(raw_value or "[]")
    except Exception:
        items = []
    if not isinstance(items, list) or not items:
        return

    existing_ids = {
        row[0]
        for row in bind.execute(sa.text("SELECT id FROM resource_exchange_posts")).fetchall()
    }
    insert_rows = []
    now = datetime.utcnow()
    for item in items:
        if not isinstance(item, dict):
            continue
        post_id = str(item.get("id") or "").strip()
        if not post_id or post_id in existing_ids:
            continue
        insert_rows.append(
            {
                "id": post_id,
                "user_id": int(item.get("user_id") or 0),
                "username": str(item.get("username") or "").strip(),
                "membership_label": str(item.get("membership_label") or "试用用户").strip() or "试用用户",
                "membership_value": int(item.get("membership_value") or 0),
                "project_name": str(item.get("project_name") or "").strip(),
                "project_intro": str(item.get("project_intro") or "").strip(),
                "contact": str(item.get("contact") or "").strip(),
                "status": str(item.get("status") or "pending").strip() or "pending",
                "created_at": _parse_iso_datetime(item.get("created_at")) or now,
                "updated_at": _parse_iso_datetime(item.get("reviewed_at")) or _parse_iso_datetime(item.get("created_at")) or now,
                "reviewed_at": _parse_iso_datetime(item.get("reviewed_at")),
                "approved_at": _parse_iso_datetime(item.get("approved_at")),
                "review_reason": str(item.get("review_reason") or "").strip() or None,
                "reviewer_id": int(item.get("reviewer_id") or 0) or None,
                "reviewer_name": str(item.get("reviewer_name") or "").strip() or None,
            }
        )

    if insert_rows:
        post_table = sa.table(
            "resource_exchange_posts",
            sa.column("id", sa.String(length=32)),
            sa.column("user_id", sa.Integer()),
            sa.column("username", sa.String(length=80)),
            sa.column("membership_label", sa.String(length=32)),
            sa.column("membership_value", sa.Integer()),
            sa.column("project_name", sa.String(length=64)),
            sa.column("project_intro", sa.String(length=255)),
            sa.column("contact", sa.String(length=120)),
            sa.column("status", sa.String(length=16)),
            sa.column("created_at", sa.DateTime()),
            sa.column("updated_at", sa.DateTime()),
            sa.column("reviewed_at", sa.DateTime()),
            sa.column("approved_at", sa.DateTime()),
            sa.column("review_reason", sa.String(length=255)),
            sa.column("reviewer_id", sa.Integer()),
            sa.column("reviewer_name", sa.String(length=80)),
        )
        op.bulk_insert(post_table, insert_rows)

    bind.execute(
        sa.text("DELETE FROM config WHERE `key` = :config_key"),
        {"config_key": _RESOURCE_EXCHANGE_CONFIG_KEY},
    )


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table("resource_exchange_posts"):
        return
    op.drop_index("ix_resource_exchange_posts_created_at", table_name="resource_exchange_posts")
    op.drop_index("ix_resource_exchange_posts_status", table_name="resource_exchange_posts")
    op.drop_index("ix_resource_exchange_posts_user_id", table_name="resource_exchange_posts")
    op.drop_table("resource_exchange_posts")
