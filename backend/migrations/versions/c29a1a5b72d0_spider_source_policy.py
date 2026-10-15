"""Add source automation policy and latest discovery error.

Revision ID: c29a1a5b72d0
Revises: e07beec8558f
"""
from alembic import op
import sqlalchemy as sa

revision = "c29a1a5b72d0"
down_revision = "e07beec8558f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("software_sources", sa.Column("automation_status", sa.Enum(
        "UNKNOWN", "ALLOWED", "MANUAL_REQUIRED", "DISABLED", native_enum=False, length=32),
        nullable=False, server_default="UNKNOWN", comment="自动访问状态 / Automation status"))
    op.add_column("software_sources", sa.Column("last_error", sa.Text(), nullable=True,
                                                comment="最近抓取错误 / Latest discovery error"))


def downgrade() -> None:
    op.drop_column("software_sources", "last_error")
    op.drop_column("software_sources", "automation_status")
