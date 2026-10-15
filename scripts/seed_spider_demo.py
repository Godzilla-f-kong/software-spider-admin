"""Opt-in helper: attach one spider source to an existing software record.

Run from project root:
  .venv\Scripts\python.exe scripts\seed_spider_demo.py --software-id 3 \
      --url https://github.com/cli/cli --adapter GITHUB_RELEASE
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select

from app.core.enums import AdapterType, SourceType
from app.db.session import SessionLocal
from app.models import Software, SoftwareSource
from app.spider.normalizers import URLNormalizer


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--software-id", type=int, required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--adapter", choices=[kind.value for kind in AdapterType], default="GITHUB_RELEASE")
    args = parser.parse_args()
    url = URLNormalizer.normalize(args.url)
    with SessionLocal() as db:
        software = db.get(Software, args.software_id)
        if software is None:
            parser.error("Software ID does not exist")
        existing = db.scalar(select(SoftwareSource).where(SoftwareSource.software_id == software.id,
                                                         SoftwareSource.source_url == url))
        if existing:
            print(f"Source already exists: #{existing.id}")
            return
        kind = AdapterType(args.adapter)
        source = SoftwareSource(software_id=software.id, source_url=url, adapter_type=kind,
                                source_type=SourceType.GITHUB if kind is AdapterType.GITHUB_RELEASE else SourceType.OTHER)
        db.add(source)
        db.commit()
        db.refresh(source)
        print(f"Created source #{source.id} for software #{software.id}; no discovery was started")


if __name__ == "__main__":
    main()
