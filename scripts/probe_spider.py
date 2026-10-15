"""Read-only source probe; does not connect to MySQL or download installers."""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.enums import AdapterType
from app.spider.adapters import SourceAdapterFactory, SourceInput
from app.spider.http import SpiderHttpClient


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--adapter", choices=[kind.value for kind in AdapterType], default="GITHUB_RELEASE")
    args = parser.parse_args()
    with SpiderHttpClient() as http:
        result = SourceAdapterFactory.create(AdapterType(args.adapter), http).discover(SourceInput(0, 0, args.url))
    print(f"releases={len(result.releases)} artifacts={result.artifact_count} links={result.link_count}")
    for release in result.releases[:5]:
        print(f"  {release.version or 'UNKNOWN'}: {len(release.artifacts)} artifacts, {len(release.links)} links")
        for link in release.links[:20]:
            print(f"    {link.provider.value} {link.link_url} access_code={link.access_code or '-'}")
    for warning in result.warnings:
        print(f"warning: {warning}")


if __name__ == "__main__":
    main()
