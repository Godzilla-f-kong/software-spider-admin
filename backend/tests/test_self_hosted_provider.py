import json

import httpx
import pytest

from app.core.config import settings
from app.storage.exceptions import StorageError
from app.storage.models import UploadRequest
from app.storage.providers.self_hosted_provider import SelfHostedPanProvider


def configure(monkeypatch):
    monkeypatch.setattr(settings, "self_hosted_base_url", "http://192.168.0.100:9000")
    monkeypatch.setattr(settings, "self_hosted_api_key", "test-service-key")
    monkeypatch.setattr(settings, "self_hosted_username", "software_spider")
    monkeypatch.setattr(settings, "self_hosted_chunk_size", 64 * 1024)
    monkeypatch.setattr(settings, "self_hosted_timeout", 4)


def test_upload_streams_chunks_then_registers_file(monkeypatch, tmp_path):
    configure(monkeypatch)
    file_path = tmp_path / "demo.zip"
    file_path.write_bytes(b"a" * (2 * 64 * 1024 + 13))
    seen_chunks = []

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Integration-Key"] == "test-service-key"
        if request.url.path.endswith("/chunk"):
            body = request.read()
            seen_chunks.append(body)
            if b'name="chunkNumber"\r\n\r\n1' in body:
                response = {"result": "第一片上传成功"}
            elif b'name="chunkNumber"\r\n\r\n2' in body:
                response = {}
            else:
                response = {"result": "上传完毕"}
                response["path"] = "M00/demo.zip"
            return httpx.Response(200, json=response)
        assert request.url.path.endswith("/complete")
        data = json.loads(request.read())
        assert data["file_arch"] == "编程调试"
        assert data["filetype"] == 5
        assert data["filesize"] == file_path.stat().st_size
        return httpx.Response(200, json={"success": True, "fileid": 42, "fileindex": "M00/demo.zip"})

    client = httpx.Client(transport=httpx.MockTransport(respond))
    provider = SelfHostedPanProvider(client=client)
    progress = []
    result = provider.upload(UploadRequest(
        artifact_id=8, local_path=file_path, remote_path="",
        progress=lambda sent, total: progress.append((sent, total)),
        metadata={"file_arch": "编程调试"},
    ))

    assert len(seen_chunks) == 3
    assert progress[-1] == (file_path.stat().st_size, file_path.stat().st_size)
    assert result.remote_file_id == "42"
    assert result.remote_path == "M00/demo.zip"
    assert result.size == file_path.stat().st_size
    provider.close()
    client.close()


def test_upload_rejects_category_outside_configured_taxonomy(monkeypatch, tmp_path):
    configure(monkeypatch)
    file_path = tmp_path / "demo.zip"
    file_path.write_bytes(b"not-empty")
    provider = SelfHostedPanProvider(client=httpx.Client(transport=httpx.MockTransport(
        lambda request: pytest.fail("request must not be sent for an invalid category")
    )))

    with pytest.raises(StorageError, match="INVALID_CATEGORY"):
        provider.upload(UploadRequest(artifact_id=8, local_path=file_path, remote_path="",
                                      metadata={"file_arch": "不存在的分类"}))
    provider.close()


@pytest.mark.parametrize(("failure", "detail"), [
    ("http", "HTTP 503"),
    ("connection", "ConnectError"),
    ("json", "invalid JSON"),
])
def test_chunk_failure_reports_safe_diagnostic(monkeypatch, tmp_path, failure, detail):
    configure(monkeypatch)
    file_path = tmp_path / "demo.zip"
    file_path.write_bytes(b"test-package")

    def respond(request: httpx.Request) -> httpx.Response:
        if failure == "http":
            return httpx.Response(503)
        if failure == "connection":
            raise httpx.ConnectError("unreachable", request=request)
        return httpx.Response(200, text="not-json")

    client = httpx.Client(transport=httpx.MockTransport(respond))
    provider = SelfHostedPanProvider(client=client)
    with pytest.raises(StorageError) as error:
        provider.upload(UploadRequest(artifact_id=8, local_path=file_path, remote_path="",
                                      metadata={"file_arch": "编程调试"}))
    assert error.value.code == "CLOUD_CHUNK_UPLOAD_FAILED"
    assert detail in error.value.message
    assert "chunk 1/1" in error.value.message
    provider.close()
    client.close()


@pytest.mark.parametrize(("failure", "detail"), [
    ("http", "HTTP 409"),
    ("connection", "ConnectError"),
    ("json", "invalid JSON"),
])
def test_metadata_failure_reports_safe_diagnostic(monkeypatch, tmp_path, failure, detail):
    configure(monkeypatch)
    file_path = tmp_path / "demo.zip"
    file_path.write_bytes(b"test-package")

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/chunk"):
            return httpx.Response(200, json={"result": "上传完毕", "path": "M00/demo.zip"})
        if failure == "http":
            return httpx.Response(409)
        if failure == "connection":
            raise httpx.ConnectError("unreachable", request=request)
        return httpx.Response(200, text="not-json")

    client = httpx.Client(transport=httpx.MockTransport(respond))
    provider = SelfHostedPanProvider(client=client)
    with pytest.raises(StorageError) as error:
        provider.upload(UploadRequest(artifact_id=8, local_path=file_path, remote_path="",
                                      metadata={"file_arch": "编程调试"}))
    assert error.value.code == "CLOUD_METADATA_FAILED"
    assert detail in error.value.message
    provider.close()
    client.close()
