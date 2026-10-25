"""Track automatic download scheduling for completed candidate crawls.

Revision ID: a92c0db81f30
Revises: f125a10d9c34
"""
from alembic import op
import sqlalchemy as sa

revision = "a92c0db81f30"
down_revision = "f125a10d9c34"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("auto_download_processed", sa.Boolean(), nullable=False,
                                     server_default=sa.false(), comment="自动下载队列是否已处理"))


def downgrade() -> None:
    op.drop_column("jobs", "auto_download_processed")
