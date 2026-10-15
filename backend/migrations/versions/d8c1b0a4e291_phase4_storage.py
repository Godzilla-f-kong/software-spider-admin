"""Phase 4 storage accounts, upload and share lifecycle.

Revision ID: d8c1b0a4e291
Revises: a71c9f3d2e40
"""
from alembic import op
import sqlalchemy as sa

revision = "d8c1b0a4e291"
down_revision = "a71c9f3d2e40"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("artifact_storage", sa.Column("remote_parent_id", sa.String(255), comment="Remote parent directory ID / 远程父目录 ID"))
    op.add_column("artifact_storage", sa.Column("share_password", sa.String(100), comment="Share extraction password / 分享提取密码"))
    op.add_column("artifact_storage", sa.Column("share_id", sa.String(255), comment="Provider share ID / 网盘分享 ID"))
    op.add_column("artifact_storage", sa.Column("upload_status", sa.Enum("PENDING", "UPLOADING", "SUCCESS", "FAILED", native_enum=False, length=32), nullable=False, server_default="PENDING", comment="Upload lifecycle / 上传状态"))
    op.add_column("artifact_storage", sa.Column("share_status", sa.Enum("NONE", "CREATING", "CREATED", "EXPIRED", "DISABLED", native_enum=False, length=32), nullable=False, server_default="NONE", comment="Share lifecycle / 分享状态"))
    op.create_table("storage_accounts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="Account ID / 账号 ID"),
        sa.Column("provider", sa.Enum("LOCAL", "BAIDU", "PAN123", "SELF_HOSTED", "S3", "OTHER", native_enum=False, length=32), nullable=False, comment="Storage provider / 存储服务商"),
        sa.Column("name", sa.String(100), nullable=False, comment="Account display name / 账号显示名"),
        sa.Column("encrypted_access_token", sa.Text(), nullable=False, comment="Encrypted OAuth access token / 加密访问令牌"),
        sa.Column("encrypted_refresh_token", sa.Text(), nullable=False, comment="Encrypted OAuth refresh token / 加密刷新令牌"),
        sa.Column("expires_at", sa.DateTime(), nullable=False, comment="Token expiry in Beijing time / 北京时间到期"),
        sa.Column("status", sa.Enum("ACTIVE", "EXPIRED", "DISABLED", native_enum=False, length=32), nullable=False, server_default="ACTIVE", comment="Account status / 账号状态"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="Created at Beijing time / 北京时间创建"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="Updated at Beijing time / 北京时间更新"),
        sa.UniqueConstraint("provider", "name", name="uq_storage_accounts_provider_name"),
        comment="加密存储的云存储授权 / Encrypted provider credentials")
    op.add_column("artifact_storage", sa.Column("account_id", sa.BigInteger(), nullable=True,
        comment="Storage account ID / 存储账号 ID"))
    op.create_index("ix_artifact_storage_account_id", "artifact_storage", ["account_id"])
    op.create_foreign_key("fk_artifact_storage_account_id_storage_accounts", "artifact_storage", "storage_accounts", ["account_id"], ["id"], ondelete="RESTRICT")


def downgrade() -> None:
    op.drop_constraint("fk_artifact_storage_account_id_storage_accounts", "artifact_storage", type_="foreignkey")
    op.drop_index("ix_artifact_storage_account_id", table_name="artifact_storage")
    op.drop_column("artifact_storage", "account_id")
    op.drop_table("storage_accounts")
    for name in ("share_status", "upload_status", "share_id", "share_password", "remote_parent_id"):
        op.drop_column("artifact_storage", name)
