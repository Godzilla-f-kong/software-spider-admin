"""Store cloud share and download entry links separately from artifacts.

Revision ID: f84d7c2b1a90
Revises: c29a1a5b72d0
"""
from alembic import op
import sqlalchemy as sa

revision = "f84d7c2b1a90"
down_revision = "c29a1a5b72d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "download_links",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="Primary key"),
        sa.Column("software_id", sa.BigInteger(), sa.ForeignKey("software.id", ondelete="RESTRICT"), nullable=False, comment="Software ID"),
        sa.Column("source_id", sa.BigInteger(), sa.ForeignKey("software_sources.id", ondelete="RESTRICT"), nullable=False, comment="Source ID"),
        sa.Column("release_id", sa.BigInteger(), sa.ForeignKey("software_releases.id", ondelete="RESTRICT"), nullable=True, comment="Optional release ID"),
        sa.Column("provider", sa.Enum("QUARK", "XUNLEI", "BAIDU", "PAN123", "ALIYUN", "LANZOU", "OTHER", native_enum=False, length=32), nullable=False, comment="Cloud or download provider"),
        sa.Column("link_type", sa.Enum("PAN_SHARE", "DOWNLOAD_PAGE", "DIRECT_FILE", native_enum=False, length=32), nullable=False, comment="Share or download entry type"),
        sa.Column("link_url", sa.String(2048), nullable=False, comment="Discovered link URL"),
        sa.Column("source_page_url", sa.String(2048), nullable=True, comment="Page where the link was found"),
        sa.Column("access_code", sa.String(64), nullable=True, comment="Access code shown on source page"),
        sa.Column("label", sa.String(255), nullable=True, comment="Link label on page"),
        sa.Column("context_text", sa.Text(), nullable=True, comment="Nearby source page text"),
        sa.Column("review_status", sa.Enum("DISCOVERED", "REVIEWED", "IGNORED", native_enum=False, length=32), nullable=False, comment="Human review status"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="Creation time in UTC"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="Last update time in UTC"),
        comment="Discovered cloud share and download entry links",
    )
    op.create_index("ix_download_links_software_id", "download_links", ["software_id"])
    op.create_index("ix_download_links_source_id", "download_links", ["source_id"])
    op.create_index("ix_download_links_release_id", "download_links", ["release_id"])
    op.create_index("ix_download_links_source_release", "download_links", ["source_id", "release_id"])


def downgrade() -> None:
    op.drop_index("ix_download_links_source_release", table_name="download_links")
    op.drop_index("ix_download_links_release_id", table_name="download_links")
    op.drop_index("ix_download_links_source_id", table_name="download_links")
    op.drop_index("ix_download_links_software_id", table_name="download_links")
    op.drop_table("download_links")
