"""Phase 3 download and verification metadata.

Revision ID: c641baf2e907
Revises: b319a76e52d4
"""
from alembic import op
import sqlalchemy as sa

revision = "c641baf2e907"
down_revision = "b319a76e52d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("software_artifacts", sa.Column("resolved_url", sa.String(2048), nullable=True,
        comment="Final validated download URL after redirects"))
    op.add_column("software_artifacts", sa.Column("downloaded_at", sa.DateTime(), nullable=True,
        comment="Downloaded at Asia/Shanghai"))
    op.add_column("software_artifacts", sa.Column("verified_at", sa.DateTime(), nullable=True,
        comment="Verified at Asia/Shanghai"))
    op.add_column("software_artifacts", sa.Column("manual_reviewed_at", sa.DateTime(), nullable=True,
        comment="Manually reviewed at Asia/Shanghai"))
    op.add_column("software_artifacts", sa.Column("verification_details", sa.JSON(), nullable=True,
        comment="Structured verification checks and metadata JSON"))
    op.add_column("software_artifacts", sa.Column("redistribution_status", sa.Enum("UNKNOWN", "ALLOWED", "PROHIBITED", native_enum=False, length=32), nullable=False,
        server_default="UNKNOWN", comment="Permission to redistribute the artifact"))


def downgrade() -> None:
    for name in ("redistribution_status", "verification_details", "manual_reviewed_at",
                 "verified_at", "downloaded_at", "resolved_url"):
        op.drop_column("software_artifacts", name)
