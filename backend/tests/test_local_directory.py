import pytest
from fastapi import HTTPException, Request
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.api.v1 import open_storage_directory, serialize, RESOURCES
from app.core.config import settings
from app.core.enums import Architecture, OperatingSystem, PackageType, StorageProviderType
from app.db.base import Base
from app.models import ArtifactStorage, Software, SoftwareArtifact, SoftwareRelease, SoftwareVariant
from app.storage.local_directory import archived_file_for_storage


@compiles(BigInteger, "sqlite")
def sqlite_bigint(_type, _compiler, **_kwargs):
    return "INTEGER"


def request(host: str = "127.0.0.1") -> Request:
    return Request({"type": "http", "client": (host, 12345)})


def test_open_local_storage_directory_uses_validated_archive_path(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_root", str(tmp_path))
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        software = Software(name="Sample", slug="sample")
        db.add(software)
        db.flush()
        release = SoftwareRelease(software_id=software.id, version="1.0")
        db.add(release)
        db.flush()
        variant = SoftwareVariant(release_id=release.id, os=OperatingSystem.WINDOWS, architecture=Architecture.X64)
        db.add(variant)
        db.flush()
        artifact = SoftwareArtifact(variant_id=variant.id, filename="sample.zip", package_type=PackageType.ZIP,
                                    local_path="archive/sample/1.0/windows/x64/sample.zip")
        db.add(artifact)
        db.flush()
        storage = ArtifactStorage(artifact_id=artifact.id, provider=StorageProviderType.LOCAL,
                                  remote_path="C:/untrusted/path")
        db.add(storage)
        db.commit()
        path = tmp_path / artifact.local_path
        path.parent.mkdir(parents=True)
        path.write_bytes(b"test")

        opened = []
        monkeypatch.setattr("app.api.v1.open_local_directory", opened.append)
        assert serialize(RESOURCES[7], storage, db)["local_exists"] is True
        assert open_storage_directory(storage.id, request(), db) == {"opened": True}
        assert opened == [path]

        with pytest.raises(HTTPException) as forbidden:
            open_storage_directory(storage.id, request("192.0.2.10"), db)
        assert forbidden.value.status_code == 403

        artifact.local_path = "archive/../outside.zip"
        db.commit()
        assert archived_file_for_storage(storage) is None
        assert serialize(RESOURCES[7], storage, db)["local_exists"] is False
        with pytest.raises(HTTPException) as missing:
            open_storage_directory(storage.id, request(), db)
        assert missing.value.status_code == 404

        storage.provider = StorageProviderType.BAIDU
        db.commit()
        with pytest.raises(HTTPException) as unsupported:
            open_storage_directory(storage.id, request(), db)
        assert unsupported.value.status_code == 409
