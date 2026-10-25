import hashlib
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from cryptography.fernet import Fernet
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.enums import Architecture, OperatingSystem, PackageType, StorageProviderType, UploadStatus
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Software, SoftwareArtifact, SoftwareRelease, SoftwareVariant
from app.storage.exceptions import StorageError
from app.storage.models import ShareResult, UploadRequest, UploadResult
from app.storage.providers.baidu_provider import BaiduPanProvider
from app.storage.providers.local_provider import LocalStorageProvider
from app.storage.service import (access_token, create_share, disable_share, queue_upload,
                                 run_upload, save_oauth_account)


@compiles(BigInteger, "sqlite")
def sqlite_bigint(_type, _compiler, **_kwargs):
    return "INTEGER"


def test_local_provider_validates_archive(tmp_path):
    from app.storage.archive import ArchiveManager
    manager = ArchiveManager(tmp_path)
    relative = "archive/demo/app.zip"
    path = manager.resolve_relative(relative)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"archive")
    provider = LocalStorageProvider(manager)
    assert provider.get_status(relative)
    assert provider.upload(UploadRequest(1, path, relative)).size == 7
    with pytest.raises(StorageError, match="LOCAL_FILE_MISSING"):
        provider.upload(UploadRequest(1, tmp_path / "wrong.zip", relative))


def test_baidu_slice_upload_and_share(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "baidu_app_id", "123456")
    path = tmp_path / "app.zip"
    path.write_bytes(b"abcdefgh")
    hashes = [hashlib.md5(x).hexdigest() for x in (b"abcd", b"efgh")]
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if request.url.params.get("method") == "precreate":
            return httpx.Response(200, json={"errno": 0, "uploadid": "upload-1", "block_list": [0, 1]})
        if request.url.params.get("method") == "locateupload":
            return httpx.Response(200, json={"error_code": 0, "servers": [{"server": "https://c3.pcs.baidu.com"}]})
        if request.url.params.get("method") == "upload":
            return httpx.Response(200, json={"errno": 0, "md5": hashes[int(request.url.params["partseq"])]})
        if request.url.params.get("method") == "create":
            return httpx.Response(200, json={"errno": 0, "fs_id": 123, "path": "/apps/demo/a.zip"})
        if request.url.path.endswith("/share/set"):
            return httpx.Response(200, json={"errno": 0, "data": {"share_id": 99, "link": "https://pan.baidu.com/s/demo", "pwd": "a1b2"}})
        return httpx.Response(404)

    provider = BaiduPanProvider(httpx.Client(transport=httpx.MockTransport(handler)), chunk_size=4)
    progress = []
    result = provider.upload(UploadRequest(1, path, "/apps/demo/a.zip", "secret", lambda sent, total: progress.append((sent, total))))
    assert result.remote_file_id == "123"
    assert progress == [(4, 8), (8, 8)]
    assert len([url for url in calls if "superfile2" in url]) == 2
    share = provider.create_share("123", "secret", "a1b2")
    assert share.share_id == "99" and share.code == "a1b2"
    with pytest.raises(StorageError, match="NOT_SUPPORTED_BY_OPEN_API"):
        provider.remove_share(share.share_id, "secret")


def test_baidu_token_refresh_does_not_expose_token(monkeypatch):
    monkeypatch.setattr(settings, "baidu_token_encryption_key", Fernet.generate_key().decode())
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        account = save_oauth_account(db, "test", {"access_token": "old-secret", "refresh_token": "refresh-secret", "expires_in": 60})
        assert "old-secret" not in account.encrypted_access_token
        class Provider:
            def refresh_token(self, token):
                assert token == "refresh-secret"
                return {"access_token": "new-secret", "refresh_token": "new-refresh", "expires_in": 3600}
        assert access_token(db, account, Provider()) == "new-secret"
        assert "new-secret" not in account.encrypted_access_token


def test_upload_job_and_share_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_root", str(tmp_path))
    monkeypatch.setattr(settings, "baidu_token_encryption_key", Fernet.generate_key().decode())
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        software = Software(name="Demo", slug="demo")
        db.add(software); db.flush()
        release = SoftwareRelease(software_id=software.id, version="1")
        db.add(release); db.flush()
        variant = SoftwareVariant(release_id=release.id, os=OperatingSystem.WINDOWS, architecture=Architecture.X64)
        db.add(variant); db.flush()
        artifact = SoftwareArtifact(variant_id=variant.id, filename="demo.zip", package_type=PackageType.ZIP,
                                    local_path="archive/demo/1/windows/x64/demo.zip")
        db.add(artifact); db.flush()
        path = tmp_path / artifact.local_path
        path.parent.mkdir(parents=True)
        path.write_bytes(b"verified")
        save_oauth_account(db, "test", {"access_token": "secret", "refresh_token": "refresh", "expires_in": 3600})
        job = queue_upload(db, artifact.id)
        assert job.status.value == "PENDING"
        with pytest.raises(StorageError, match="UPLOAD_IN_PROGRESS"):
            queue_upload(db, artifact.id)

        class Provider:
            def upload(self, request):
                assert request.access_token == "secret"
                request.progress(8, 8)
                return UploadResult(request.remote_path, "123", 8)
            def create_share(self, fs_id, token, password):
                return ShareResult("99", "https://pan.baidu.com/s/demo", password)
            def remove_share(self, share_id, token):
                assert share_id == "99"

        run_upload(db, job, Provider())
        storage = artifact.storage_locations[0]
        assert storage.provider == StorageProviderType.BAIDU
        assert storage.upload_status == UploadStatus.SUCCESS
        assert create_share(db, storage, "1234", Provider()).share_status.value == "CREATED"
        assert disable_share(db, storage, Provider()).share_status.value == "DISABLED"
        with pytest.raises(StorageError, match="ALREADY_UPLOADED"):
            queue_upload(db, artifact.id)


def test_storage_crud_keeps_managed_providers_protected():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        software = Software(name="Demo", slug="demo")
        db.add(software); db.flush()
        release = SoftwareRelease(software_id=software.id, version="1")
        db.add(release); db.flush()
        variant = SoftwareVariant(release_id=release.id, os=OperatingSystem.WINDOWS, architecture=Architecture.X64)
        db.add(variant); db.flush()
        artifact = SoftwareArtifact(variant_id=variant.id, filename="demo.zip", package_type=PackageType.ZIP)
        db.add(artifact); db.commit()
        app.dependency_overrides[get_db] = lambda: db
        try:
            client = TestClient(app)
            created_artifact = client.post("/api/v1/artifacts", json={
                "variant_id": variant.id, "package_type": "ZIP", "filename": "new.zip",
                "verification_status": "VERIFIED", "redistribution_status": "ALLOWED",
            })
            assert created_artifact.status_code == 422
            artifact_data = client.get(f"/api/v1/artifacts/{artifact.id}").json()
            assert "verification_status" not in artifact_data
            assert "redistribution_status" not in artifact_data
            assert client.post("/api/v1/storage", json={"artifact_id": artifact.id, "provider": "BAIDU"}).status_code == 422
            created = client.post("/api/v1/storage", json={"artifact_id": artifact.id, "provider": "PAN123", "remote_path": "/demo"})
            assert created.status_code == 201, created.text
            storage_id = created.json()["id"]
            updated = client.patch(f"/api/v1/storage/{storage_id}", json={"remote_path": "/demo2"})
            assert updated.status_code == 200 and updated.json()["remote_path"] == "/demo2"
            listed = client.get("/api/v1/artifacts/%s/storage" % artifact.id)
            assert listed.status_code == 200 and listed.json()["items"][0]["id"] == storage_id
        finally:
            app.dependency_overrides.clear()
