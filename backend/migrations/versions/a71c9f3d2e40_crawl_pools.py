"""Add independent website crawl pool.

Revision ID: a71c9f3d2e40
Revises: c641baf2e907
"""
from alembic import op
import sqlalchemy as sa

revision = "a71c9f3d2e40"
down_revision = "c641baf2e907"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crawl_pools",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="主键 ID / Primary key"),
        sa.Column("base_url", sa.String(2048), nullable=False, comment="人工录入的网站主页 / User supplied website home URL"),
        sa.Column("url_hash", sa.String(64), nullable=False, comment="标准化主页 URL 的 SHA-256 / Normalized home URL SHA-256"),
        sa.Column("enabled", sa.Boolean(), nullable=False, comment="是否启用 / Enabled"),
        sa.Column("max_pages", sa.Integer(), nullable=False, comment="单次扫描最多访问页面数 / Maximum pages per scan"),
        sa.Column("max_depth", sa.Integer(), nullable=False, comment="站内链接最大遍历深度 / Maximum internal link depth"),
        sa.Column("status", sa.Enum("NEW", "HEALTHY", "FAILED", "DISABLED", native_enum=False, length=32), nullable=False, comment="当前状态 / Status"),
        sa.Column("last_checked_at", sa.DateTime(), nullable=True, comment="Last Checked At (Asia/Shanghai, UTC+08:00)"),
        sa.Column("last_error", sa.Text(), nullable=True, comment="最近抓取错误 / Latest discovery error"),
        sa.Column("last_result_count", sa.Integer(), nullable=False, comment="最近一次匹配候选数 / Matches in latest scan"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="Created At (Asia/Shanghai, UTC+08:00)"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="Updated At (Asia/Shanghai, UTC+08:00)"),
        comment="人工维护的网站主页抓取池 / User managed website crawl pool",
    )
    op.create_unique_constraint("uq_crawl_pools_url_hash", "crawl_pools", ["url_hash"])


def downgrade() -> None:
    op.drop_constraint("uq_crawl_pools_url_hash", "crawl_pools", type_="unique")
    op.drop_table("crawl_pools")
