"""add license and referral

Revision ID: 9c1a2b3c4d5e
Revises: 4a9b2c7d1e6f
Create Date: 2026-03-16 23:05:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "9c1a2b3c4d5e"
down_revision = "4a9b2c7d1e6f"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    dialect = bind.dialect.name
    user_columns = {c["name"] for c in inspector.get_columns("users")}
    user_indexes = {item["name"] for item in inspector.get_indexes("users")}
    user_unique_constraints = {item["name"] for item in inspector.get_unique_constraints("users") if item.get("name")}
    if "ref_code" not in user_columns:
        op.add_column("users", sa.Column("ref_code", sa.String(length=16), nullable=True))
    if "uq_users_ref_code" not in user_indexes and "uq_users_ref_code" not in user_unique_constraints:
        op.create_index("uq_users_ref_code", "users", ["ref_code"], unique=True)
    if "referrer_id" not in user_columns:
        op.add_column("users", sa.Column("referrer_id", sa.Integer(), nullable=True))
    if dialect != "sqlite":
        foreign_keys = {item.get("name") for item in inspector.get_foreign_keys("users") if item.get("name")}
        if "fk_users_referrer" not in foreign_keys:
            op.create_foreign_key("fk_users_referrer", "users", "users", ["referrer_id"], ["id"])

    if not inspector.has_table("cdk_codes"):
        op.create_table(
            "cdk_codes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("code", sa.String(length=32), nullable=False, unique=True),
            sa.Column("card_type", sa.String(length=20), nullable=False),
            sa.Column("duration_days", sa.Integer(), nullable=False),
            sa.Column("bonus_points", sa.Integer(), server_default="0"),
            sa.Column("device_limit", sa.Integer(), server_default="1"),
            sa.Column("transfer_times", sa.Integer(), server_default="0"),
            sa.Column("transfer_times_left", sa.Integer(), server_default="0"),
            sa.Column("status", sa.Integer(), server_default="0"),
            sa.Column("activated_by", sa.Integer(), nullable=True),
            sa.Column("activated_at", sa.DateTime(), nullable=True),
            sa.Column("expire_at", sa.DateTime(), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("batch_id", sa.String(length=32), nullable=True),
            sa.Column("redeem_deadline", sa.DateTime(), nullable=True),
            sa.Column("last_transfer_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["activated_by"], ["users.id"]),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        )

    if not inspector.has_table("license_bindings"):
        op.create_table(
            "license_bindings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("code_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("device_fingerprint", sa.String(length=128), nullable=False),
            sa.Column("device_label", sa.String(length=128), nullable=True),
            sa.Column("device_info", sa.Text(), nullable=True),
            sa.Column("active", sa.Boolean(), server_default=sa.text("1")),
            sa.Column("bound_at", sa.DateTime(), nullable=True),
            sa.Column("unbound_at", sa.DateTime(), nullable=True),
            sa.Column("last_seen_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["code_id"], ["cdk_codes.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        )

    if inspector.has_table("tasks"):
        task_columns = {c["name"] for c in inspector.get_columns("tasks")}
        if "refunded" not in task_columns:
            with op.batch_alter_table("tasks") as batch_op:
                batch_op.add_column(sa.Column("refunded", sa.Boolean(), server_default=sa.text("0")))


def downgrade():
    op.drop_table("license_bindings")
    op.drop_table("cdk_codes")
    bind = op.get_bind()
    inspector = inspect(bind)
    if bind.dialect.name != "sqlite":
        foreign_keys = {item.get("name") for item in inspector.get_foreign_keys("users") if item.get("name")}
        if "fk_users_referrer" in foreign_keys:
            op.drop_constraint("fk_users_referrer", "users", type_="foreignkey")
    user_indexes = {item["name"] for item in inspector.get_indexes("users")}
    if "uq_users_ref_code" in user_indexes:
        op.drop_index("uq_users_ref_code", table_name="users")
    user_columns = {c["name"] for c in inspector.get_columns("users")}
    if "referrer_id" in user_columns:
        op.drop_column("users", "referrer_id")
    if "ref_code" in user_columns:
        op.drop_column("users", "ref_code")
