"""Target conditions and site search hints for independent candidate and URL pools.

Revision ID: f125a10d9c34
Revises: d8c1b0a4e291
"""
from alembic import op
import sqlalchemy as sa

revision = "f125a10d9c34"
down_revision = "d8c1b0a4e291"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("software_candidates", sa.Column("target_version", sa.String(100), nullable=True,
                  comment="目标软件版本 / Target version"))
    op.add_column("software_candidates", sa.Column("target_os", sa.Enum("WINDOWS", "LINUX", "MACOS", "ANDROID", "OTHER", "UNKNOWN", native_enum=False, length=32), nullable=True,
                  comment="目标操作系统 / Target OS"))
    op.add_column("software_candidates", sa.Column("target_architecture", sa.Enum("X86", "X64", "ARM", "ARM64", "UNIVERSAL", "OTHER", "UNKNOWN", native_enum=False, length=32), nullable=True,
                  comment="目标 CPU 架构 / Target CPU architecture"))
    op.add_column("crawl_pools", sa.Column("search_path_template", sa.String(1024), nullable=True,
                  comment="可选站内搜索路径模板，使用 {query} / Optional site search path"))
    op.add_column("crawl_pools", sa.Column("category_paths", sa.Text(), nullable=True,
                  comment="可选分类路径，每行一个 / Optional category paths"))


def downgrade() -> None:
    op.drop_column("crawl_pools", "category_paths")
    op.drop_column("crawl_pools", "search_path_template")
    op.drop_column("software_candidates", "target_architecture")
    op.drop_column("software_candidates", "target_os")
    op.drop_column("software_candidates", "target_version")
