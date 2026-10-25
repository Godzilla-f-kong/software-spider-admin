"""Persist software attributes through discovery, download and upload."""
from alembic import op
import sqlalchemy as sa

revision = "c301d56a8e42"
down_revision = "a92c0db81f30"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("software", sa.Column("origin_region", sa.String(32), nullable=False, server_default="UNKNOWN", comment="软件来源地区：国内/国外/未知"))
    op.add_column("software_variants", sa.Column("cpu_family", sa.String(32), nullable=False, server_default="UNKNOWN", comment="CPU 架构族：AMD/x86 或 ARM"))
    op.add_column("software_artifacts", sa.Column("install_type", sa.String(32), nullable=False, server_default="UNKNOWN", comment="安装形态：免安装/安装包"))


def downgrade() -> None:
    op.drop_column("software_artifacts", "install_type")
    op.drop_column("software_variants", "cpu_family")
    op.drop_column("software", "origin_region")
