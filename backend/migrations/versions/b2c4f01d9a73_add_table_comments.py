"""Add bilingual comments to Phase 1 tables.

Revision ID: b2c4f01d9a73
Revises: e1fd34bb5149
"""
from alembic import op

revision = "b2c4f01d9a73"
down_revision = "e1fd34bb5149"
branch_labels = None
depends_on = None

COMMENTS = {
    "software_candidates": "候选软件 / Discovered software candidates",
    "software": "软件产品 / Software products",
    "software_sources": "软件来源 / Software sources",
    "software_releases": "软件版本 / Software releases",
    "software_variants": "运行环境变体 / Release variants",
    "software_artifacts": "软件安装文件 / Software artifacts",
    "artifact_storage": "文件存储位置 / Artifact storage locations",
    "generated_content": "生成内容草稿 / Generated content drafts",
    "commerce_listings": "电商商品文案 / Commerce listings",
    "jobs": "后台任务 / Background jobs",
}


def upgrade() -> None:
    for table_name, comment in COMMENTS.items():
        op.create_table_comment(table_name, comment)


def downgrade() -> None:
    for table_name, comment in COMMENTS.items():
        op.drop_table_comment(table_name, existing_comment=comment)
