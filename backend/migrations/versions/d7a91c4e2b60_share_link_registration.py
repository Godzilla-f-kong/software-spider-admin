"""Add cloud permanent share-link registration tracking."""
from alembic import op
import sqlalchemy as sa

revision = "d7a91c4e2b60"
down_revision = "c301d56a8e42"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "share_link_submissions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False, comment="登记记录主键 / Registration record ID"),
        sa.Column("fingerprint", sa.String(64), nullable=False, comment="外链和分享码去重指纹 / External URL and share code deduplication fingerprint"),
        sa.Column("download_link_id", sa.BigInteger(), nullable=True, comment="来源下载链接记录 ID / Source download link ID"),
        sa.Column("crawl_job_id", sa.BigInteger(), nullable=True, comment="来源候选抓取任务 ID / Source candidate crawl job ID"),
        sa.Column("candidate_id", sa.BigInteger(), nullable=True, comment="关联软件候选 ID / Related software candidate ID"),
        sa.Column("software_id", sa.BigInteger(), nullable=True, comment="关联正式软件 ID / Related catalog software ID"),
        sa.Column("software_name", sa.String(255), nullable=False, comment="登记到云盘的软件名称 / Software name sent to cloud"),
        sa.Column("provider", sa.String(32), nullable=True, comment="原始网盘平台 / Original share provider"),
        sa.Column("external_url", sa.String(2048), nullable=False, comment="原始网盘分享 URL / Original cloud share URL"),
        sa.Column("extract_code", sa.String(64), nullable=True, comment="原始网盘提取码 / Original cloud share code"),
        sa.Column("source_page_url", sa.String(2048), nullable=True, comment="发现链接的网页 URL / Page where link was discovered"),
        sa.Column("filename", sa.String(255), nullable=True, comment="云盘展示文件名 / Display filename in cloud"),
        sa.Column("file_arch", sa.String(64), nullable=True, comment="云盘文件分类 / Cloud file category"),
        sa.Column("os", sa.String(64), nullable=True, comment="目标操作系统 / Target operating system"),
        sa.Column("architecture", sa.String(64), nullable=True, comment="目标 CPU 架构 / Target CPU architecture"),
        sa.Column("md5", sa.String(32), nullable=True, comment="文件 MD5 / File MD5"),
        sa.Column("install_type", sa.Integer(), nullable=True, comment="安装方式 / Installation type"),
        sa.Column("filesize", sa.BigInteger(), nullable=True, comment="文件大小（字节）/ File size in bytes"),
        sa.Column("filetype", sa.Integer(), server_default="5", nullable=False, comment="云盘文件类型编号 / Cloud file type identifier"),
        sa.Column("status", sa.String(32), server_default="INCOMPLETE", nullable=False, comment="分享链接登记状态 / Share link registration status"),
        sa.Column("validation_errors", sa.JSON(), nullable=True, comment="完整性检查问题 / Completeness validation issues"),
        sa.Column("cloud_record_id", sa.BigInteger(), nullable=True, comment="云盘永久分享记录 ID / Cloud permanent share record ID"),
        sa.Column("cloud_token", sa.String(64), nullable=True, comment="云盘生成的分享 token / Cloud generated share token"),
        sa.Column("cloud_link", sa.String(2048), nullable=True, comment="云盘生成的永久分享链接 / Cloud generated permanent share URL"),
        sa.Column("cloud_reused", sa.Boolean(), nullable=True, comment="云盘是否复用了已有记录 / Whether the cloud reused an existing record"),
        sa.Column("cloud_response", sa.JSON(), nullable=True, comment="经过筛选的云盘响应字段 / Selected cloud response fields"),
        sa.Column("error_message", sa.Text(), nullable=True, comment="登记失败或待核查原因 / Registration error or review reason"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="创建时间（北京时间）/ Created at Asia/Shanghai"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="更新时间（北京时间）/ Updated at Asia/Shanghai"),
        sa.ForeignKeyConstraint(["candidate_id"], ["software_candidates.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["crawl_job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["download_link_id"], ["download_links.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["software_id"], ["software.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("download_link_id", name="uq_share_link_submissions_download_link"),
        sa.UniqueConstraint("fingerprint", name="uq_share_link_submissions_fingerprint"),
        comment="外部网盘分享链接登记记录 / External cloud share link registration records",
    )
    op.create_index("ix_share_link_submissions_status_created", "share_link_submissions", ["status", "created_at"])
    op.create_index("ix_share_link_submissions_download_link_id", "share_link_submissions", ["download_link_id"])
    op.create_index("ix_share_link_submissions_crawl_job_id", "share_link_submissions", ["crawl_job_id"])
    op.create_index("ix_share_link_submissions_candidate_id", "share_link_submissions", ["candidate_id"])
    op.create_index("ix_share_link_submissions_software_id", "share_link_submissions", ["software_id"])


def downgrade() -> None:
    op.drop_table("share_link_submissions")
