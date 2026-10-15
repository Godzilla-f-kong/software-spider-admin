"""End-to-end API smoke test. Requires a running local backend and MySQL.

Creates a uniquely named chain and removes only records created by this test.
"""
import json
from pathlib import Path
import sys
import uuid
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import SessionLocal
from app.models import (ArtifactStorage, CommerceListing, GeneratedContent, Job, Software,
                        SoftwareArtifact, SoftwareCandidate, SoftwareRelease, SoftwareSource, SoftwareVariant)

BASE = "http://127.0.0.1:8000/api/v1"


def call(method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
    body = json.dumps(payload).encode() if payload is not None else None
    request = Request(BASE + path, data=body, method=method,
                      headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=15) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, json.load(error)


def require(method: str, path: str, payload: dict | None = None, expected: int = 200) -> dict:
    status, result = call(method, path, payload)
    assert status == expected, (method, path, status, result)
    return result


def main() -> None:
    marker = uuid.uuid4().hex[:12]
    created: list[tuple[type, int]] = []

    def create(path: str, model: type, payload: dict) -> dict:
        record = require("POST", path, payload, 201)
        created.append((model, record["id"]))
        return record

    try:
        assert require("GET", "/health")["status"] == "ok"
        candidate = create("/candidates", SoftwareCandidate, {"name": f"Smoke {marker}", "category": "Test"})
        software = require("POST", f"/candidates/{candidate['id']}/accept")
        created.append((Software, software["id"]))
        assert require("GET", f"/candidates/{candidate['id']}")["software_id"] == software["id"]
        assert call("POST", f"/candidates/{candidate['id']}/accept")[0] == 409
        source = create("/sources", SoftwareSource, {"software_id": software["id"], "source_type": "OFFICIAL", "source_url": "https://example.org"})
        release = create("/releases", SoftwareRelease, {"software_id": software["id"], "version": "1.0", "is_latest": True})
        assert call("POST", "/releases", {"software_id": software["id"], "version": "1.0"})[0] == 409
        for os, arch in [("WINDOWS", "X64"), ("WINDOWS", "ARM64"), ("LINUX", "X64")]:
            variant = create("/variants", SoftwareVariant, {"release_id": release["id"], "os": os, "architecture": arch})
            if os == "WINDOWS" and arch == "X64":
                artifact = create("/artifacts", SoftwareArtifact, {"variant_id": variant["id"], "package_type": "EXE", "filename": f"smoke-{marker}.exe", "source_url": "https://example.org/file.exe"})
        storage = create("/storage", ArtifactStorage, {"artifact_id": artifact["id"], "provider": "LOCAL"})
        content = create("/content", GeneratedContent, {"software_id": software["id"], "content_type": "WEBSITE", "title": "Draft"})
        listing = create("/listings", CommerceListing, {"software_id": software["id"], "platform": "XIANYU", "title": "Draft listing", "generated_content_id": content["id"]})
        job = require("POST", f"/artifacts/{artifact['id']}/download")
        created.append((Job, job["id"]))
        assert job["status"] == "PENDING" and job["job_type"] == "DOWNLOAD"
        assert require("GET", f"/artifacts/{artifact['id']}")["download_status"] == "QUEUED"
        assert require("GET", f"/jobs/{job['id']}")["status"] == "PENDING"
        assert require("GET", "/dashboard")["software"] >= 1
        assert require("GET", f"/software/{software['id']}/releases")["total"] == 1
        assert require("GET", f"/software/{software['id']}/sources")["total"] == 1
        assert require("GET", "/artifacts?page=1&page_size=1")["page_size"] == 1
        require("POST", f"/software/{software['id']}/archive")
        assert require("GET", f"/software/{software['id']}")["status"] == "ARCHIVED"
        print("API smoke flow passed")
    finally:
        order = [Job, CommerceListing, GeneratedContent, ArtifactStorage, SoftwareArtifact,
                 SoftwareVariant, SoftwareRelease, SoftwareSource, SoftwareCandidate, Software]
        with SessionLocal.begin() as db:
            for model in order:
                for created_model, item_id in created:
                    if created_model is model:
                        item = db.get(model, item_id)
                        if item is not None:
                            db.delete(item)
        print("Temporary smoke records removed")


if __name__ == "__main__":
    main()
