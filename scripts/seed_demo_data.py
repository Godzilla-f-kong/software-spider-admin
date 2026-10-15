"""Optional demo data. Run from backend with ..\.venv\Scripts\python.exe ..\scripts\seed_demo_data.py."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import select

from app.core import enums as e
from app.db.session import SessionLocal
from app.models import Software, SoftwareArtifact, SoftwareRelease, SoftwareVariant


def main() -> None:
    with SessionLocal.begin() as db:
        existing = db.scalar(select(Software).where(Software.slug == "7-zip"))
        if existing:
            print(f"7-Zip already exists: {existing.id}")
            return
        software = Software(name="7-Zip", slug="7-zip", developer="Igor Pavlov", category="Compression", status=e.SoftwareStatus.ACTIVE)
        db.add(software)
        db.flush()
        release = SoftwareRelease(software_id=software.id, version="24.09", is_latest=True, status=e.ReleaseStatus.READY)
        db.add(release)
        db.flush()
        variant = SoftwareVariant(release_id=release.id, os=e.OperatingSystem.WINDOWS, architecture=e.Architecture.X64)
        db.add(variant)
        db.flush()
        db.add(SoftwareArtifact(variant_id=variant.id, package_type=e.PackageType.EXE, filename="7z2409-x64.exe"))
        print(f"Created demo software {software.id}")


if __name__ == "__main__":
    main()
