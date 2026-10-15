"""Persist editable settings and use Beijing wall-clock timestamps.

Revision ID: b319a76e52d4
Revises: f84d7c2b1a90
"""
from alembic import op
import sqlalchemy as sa

revision = "b319a76e52d4"
down_revision = "f84d7c2b1a90"
branch_labels = None
depends_on = None

TIME_COLUMNS = {
    "software_candidates": ("created_at", "updated_at"),
    "software": ("created_at", "updated_at"),
    "software_sources": ("last_checked_at", "last_success_at", "created_at", "updated_at"),
    "software_releases": ("created_at", "updated_at"),
    "software_variants": ("created_at", "updated_at"),
    "software_artifacts": ("created_at", "updated_at"),
    "artifact_storage": ("created_at", "updated_at"),
    "generated_content": ("created_at", "updated_at"),
    "commerce_listings": ("generated_at", "reviewed_at", "published_at", "created_at", "updated_at"),
    "jobs": ("started_at", "finished_at", "created_at", "updated_at"),
    "download_links": ("created_at", "updated_at"),
}


def _shift(hours: int) -> None:
    for table, columns in TIME_COLUMNS.items():
        assignments = ", ".join(f"`{name}` = DATE_ADD(`{name}`, INTERVAL {hours} HOUR)" for name in columns)
        op.execute(f"UPDATE `{table}` SET {assignments}")


def _comments(timezone_label: str) -> None:
    for table, columns in TIME_COLUMNS.items():
        for name in columns:
            op.alter_column(table, name, existing_type=sa.DateTime(),
                            existing_nullable=name not in {"created_at", "updated_at"},
                            comment=f"{name.replace('_', ' ').title()} ({timezone_label})")


def upgrade() -> None:
    _shift(8)
    _comments("Asia/Shanghai, UTC+08:00")
    op.create_table(
        "system_settings",
        sa.Column("id", sa.BigInteger(), primary_key=True, comment="Primary key"),
        sa.Column("data", sa.JSON(), nullable=False, comment="Non-secret editable settings JSON"),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  comment="Created At (Asia/Shanghai, UTC+08:00)"),
        sa.Column("updated_at", sa.DateTime(), nullable=False,
                  comment="Updated At (Asia/Shanghai, UTC+08:00)"),
        comment="Editable non-secret system settings",
    )


def downgrade() -> None:
    op.drop_table("system_settings")
    _shift(-8)
    _comments("UTC")
