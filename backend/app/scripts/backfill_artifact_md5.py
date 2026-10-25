"""Backfill MD5 values for already archived artifacts."""
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import SoftwareArtifact
from app.storage.archive import ArchiveManager
from app.storage.providers.self_hosted_provider import SelfHostedPanProvider


def main() -> None:
    manager = ArchiveManager()
    updated = missing = 0
    with SessionLocal() as db:
        artifacts = db.scalars(select(SoftwareArtifact).where(
            SoftwareArtifact.md5.is_(None), SoftwareArtifact.local_path.is_not(None)
        ).order_by(SoftwareArtifact.id)).all()
        for artifact in artifacts:
            try:
                path = manager.resolve_relative(artifact.local_path)
            except ValueError:
                missing += 1
                continue
            if not path.is_file():
                missing += 1
                continue
            artifact.md5 = SelfHostedPanProvider._md5(path)
            updated += 1
            if updated % 100 == 0:
                db.commit()
        db.commit()
    print(f"MD5 backfill complete: updated={updated}, missing_files={missing}")


if __name__ == "__main__":
    main()
