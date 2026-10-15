import hashlib
import json
import io
import struct
import zipfile

import httpx
import pytest

from app.core.config import settings
from app.core.enums import Architecture, PackageType, VerificationStatus
from app.core.enums import OperatingSystem
from app.db.base import Base
from app.models import Software, SoftwareArtifact, SoftwareRelease, SoftwareVariant
from app.api.v1 import review_artifact
from app.downloader.staging import StagingManager
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from app.downloader.base import DownloadRequest
from app.downloader.errors import DownloadError
from app.downloader.http_downloader import HttpDownloader
from app.downloader.policy import DownloadPolicy, safe_filename
from app.storage.archive import ArchiveManager
from app.verification.service import VerificationService, hashes, pe_architecture


@pytest.fixture(autouse=True)
def limits(monkeypatch):
    monkeypatch.setattr(settings, "download_min_free_space", 0)
    monkeypatch.setattr(settings, "download_max_file_size", 0)
    monkeypatch.setattr(settings, "download_max_retries", 0)


def downloader(handler):
    return HttpDownloader(transport=httpx.MockTransport(handler), policy=DownloadPolicy(allow_private=True, domains="example.test"))


def request(tmp_path):
    return DownloadRequest(1, "https://example.test/app.zip", "app.zip", tmp_path / "artifact.part")


def test_stream_progress_hash_and_filename(tmp_path):
    data = b"PK\x03\x04" + b"x" * 100
    seen = []
    result = downloader(lambda req: httpx.Response(200, headers={"Content-Length": str(len(data)),
        "Content-Disposition": 'attachment; filename="../../bad.zip"'}, content=data)).download(
        request(tmp_path), seen.append, lambda: False)
    assert result.file_size == len(data)
    assert result.filename == "bad.zip"
    assert seen[-1].downloaded == len(data)
    assert hashes(result.path)[0] == hashlib.sha256(data).hexdigest()


def test_resume_206_and_fallback_200(tmp_path):
    target = request(tmp_path)
    target.part_path.write_bytes(b"ABC")
    target.part_path.with_suffix(".json").write_text(json.dumps({"url": target.url, "validator": None}), encoding="utf-8")
    def partial(req):
        assert req.headers["range"] == "bytes=3-"
        return httpx.Response(206, headers={"Content-Range": "bytes 3-5/6", "Content-Length": "3"}, content=b"DEF")
    downloader(partial).download(target, lambda _: None, lambda: False)
    assert target.part_path.read_bytes() == b"ABCDEF"
    target.part_path.with_suffix(".json").write_text(json.dumps({"url": target.url, "validator": None}), encoding="utf-8")
    downloader(lambda _: httpx.Response(200, content=b"NEW")).download(target, lambda _: None, lambda: False)
    assert target.part_path.read_bytes() == b"NEW"


def test_redirect_guard_and_http_errors(tmp_path):
    with pytest.raises(DownloadError, match="REDIRECT_BLOCKED"):
        downloader(lambda _: httpx.Response(302, headers={"Location": "http://127.0.0.1/private"})).download(
            request(tmp_path), lambda _: None, lambda: False)
    for status in (403, 404, 429):
        with pytest.raises(DownloadError, match=f"HTTP_{status}"):
            downloader(lambda _, status=status: httpx.Response(status)).download(request(tmp_path), lambda _: None, lambda: False)


def test_redirect_to_public_cdn(tmp_path):
    seen = []
    policy = DownloadPolicy(allow_private=True, domains="example.test", redirect_domains="cdn.test")
    def handler(req):
        seen.append(str(req.url))
        if req.url.host == "example.test":
            return httpx.Response(302, headers={"Location": "https://cdn.test/app.zip"})
        return httpx.Response(200, content=b"PK\x03\x04ok")
    result = HttpDownloader(transport=httpx.MockTransport(handler), policy=policy).download(
        request(tmp_path), lambda _: None, lambda: False)
    assert result.resolved_url == "https://cdn.test/app.zip"
    assert len(seen) == 2


def test_timeout_and_retry(tmp_path, monkeypatch):
    with pytest.raises(DownloadError, match="TIMEOUT"):
        downloader(lambda _: (_ for _ in ()).throw(httpx.ConnectTimeout("timeout"))).download(
            request(tmp_path), lambda _: None, lambda: False)
    monkeypatch.setattr(settings, "download_max_retries", 1)
    monkeypatch.setattr("app.downloader.http_downloader.time.sleep", lambda _: None)
    calls = []
    def handler(_):
        calls.append(1)
        return httpx.Response(503 if len(calls) == 1 else 200, content=b"ok")
    downloader(handler).download(request(tmp_path), lambda _: None, lambda: False)
    assert len(calls) == 2


def test_invalid_resume_content_range(tmp_path):
    target = request(tmp_path)
    target.part_path.write_bytes(b"ABC")
    target.part_path.with_suffix(".json").write_text(json.dumps({"url": target.url, "validator": None}), encoding="utf-8")
    with pytest.raises(DownloadError, match="CONTENT_LENGTH_MISMATCH"):
        downloader(lambda _: httpx.Response(206, headers={"Content-Range": "bytes 2-4/5"}, content=b"DEF")).download(
            target, lambda _: None, lambda: False)


def test_size_cancel_and_length(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "download_max_file_size", 2)
    with pytest.raises(DownloadError, match="MAX_FILE_SIZE_EXCEEDED"):
        downloader(lambda _: httpx.Response(200, content=b"123")).download(request(tmp_path), lambda _: None, lambda: False)
    monkeypatch.setattr(settings, "download_max_file_size", 0)
    with pytest.raises(DownloadError, match="CANCELLED"):
        downloader(lambda _: httpx.Response(200, content=b"123")).download(request(tmp_path), lambda _: None, lambda: True)
    with pytest.raises(DownloadError, match="CONTENT_LENGTH_MISMATCH"):
        downloader(lambda _: httpx.Response(200, headers={"Content-Length": "4"}, content=b"123")).download(request(tmp_path), lambda _: None, lambda: False)


def test_safety_and_archive_paths(tmp_path):
    assert safe_filename("..\\..\\CON.exe") == "_CON.exe"
    with pytest.raises(DownloadError, match="UNSUPPORTED_PROTOCOL"):
        DownloadPolicy(allow_private=False).validate("file:///secret")
    with pytest.raises(DownloadError, match="URL_BLOCKED"):
        DownloadPolicy(allow_private=False).validate("http://127.0.0.1/private")
    relative = ArchiveManager(tmp_path).archive_relative("../evil", "..\\v1", "WINDOWS", "X64", "..\\app.exe")
    assert str(relative).startswith("archive") and ".." not in relative.parts


def test_zip_html_and_corrupt_archive(tmp_path):
    path = tmp_path / "app.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("readme.txt", "hello")
    valid = VerificationService().verify(path, package_type=PackageType.ZIP,
        expected_architecture=Architecture.X64, expected_version="1.2.3", filename="app-1.2.3.zip")
    assert valid.status is VerificationStatus.MANUAL_REVIEW
    assert any(check["name"] == "ARCHIVE" and check["status"] == "PASS" for check in valid.checks)
    path.write_bytes(b"<html>blocked</html>")
    html = VerificationService().verify(path, package_type=PackageType.ZIP,
        expected_architecture=Architecture.X64, expected_version="1.2.3", filename="app.zip")
    assert html.status is VerificationStatus.REJECTED
    path.write_bytes(b"PK\x03\x04broken")
    corrupt = VerificationService().verify(path, package_type=PackageType.ZIP,
        expected_architecture=Architecture.X64, expected_version="1.2.3", filename="app.zip")
    assert corrupt.status is VerificationStatus.REJECTED


def test_pe_machine(tmp_path):
    path = tmp_path / "tiny.exe"
    data = bytearray(128)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3c, 0x50)
    data[0x50:0x54] = b"PE\0\0"
    struct.pack_into("<H", data, 0x54, 0xaa64)
    path.write_bytes(data)
    assert pe_architecture(path) is Architecture.ARM64


@compiles(BigInteger, "sqlite")
def sqlite_bigint(_type, _compiler, **_kwargs):
    return "INTEGER"


def test_manual_review_approval_archives_and_records_local_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_root", str(tmp_path))
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        software = Software(name="Test", slug="test")
        db.add(software)
        db.flush()
        release = SoftwareRelease(software_id=software.id, version="1.0")
        db.add(release)
        db.flush()
        variant = SoftwareVariant(release_id=release.id, os=OperatingSystem.WINDOWS, architecture=Architecture.X64)
        db.add(variant)
        db.flush()
        artifact = SoftwareArtifact(variant_id=variant.id, filename="test-1.0.zip", package_type=PackageType.ZIP,
                                    verification_status=VerificationStatus.MANUAL_REVIEW)
        db.add(artifact)
        db.commit()
        staged = StagingManager().complete(artifact.id)
        staged.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(staged, "w") as archive:
            archive.writestr("README.txt", "hello")
        result = review_artifact(artifact.id, "approve", db)
        assert result["verification_status"] == "VERIFIED"
        assert result["local_exists"] is True
        assert result["sha256"] == hashlib.sha256((tmp_path / result["local_path"]).read_bytes()).hexdigest()
