"""repair tasks refunded column

Revision ID: 26b0740509b7
Revises: e1f2g3h4i5j6
Create Date: 2026-03-18 12:38:26.806900
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "26b0740509b7"
down_revision = "e1f2g3h4i5j6"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    task_columns = {c["name"] for c in inspector.get_columns("tasks")}
    if "refunded" not in task_columns:
        with op.batch_alter_table("tasks") as batch_op:
            batch_op.add_column(sa.Column("refunded", sa.Boolean(), server_default=sa.text("0")))


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    task_columns = {c["name"] for c in inspector.get_columns("tasks")}
    if "refunded" in task_columns:
        with op.batch_alter_table("tasks") as batch_op:
            batch_op.drop_column("refunded")
