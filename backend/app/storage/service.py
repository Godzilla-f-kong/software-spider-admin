"""Storage business rules and OAuth account persistence; providers never use SQL."""
from datetime import timedelta
from pathlib import Path
import time

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import (DownloadStatus, JobStatus, JobType, ShareStatus,
                            StorageAccountStatus, StorageProviderType, StorageStatus, UploadStatus)
from app.db.base import beijing_now
from app.models import ArtifactStorage, Job, SoftwareArtifact, StorageAccount
from app.downloader.policy import safe_component, safe_filename
from app.storage.archive import ArchiveManager
from app.downloader.staging import StagingManager
from app.storage.exceptions import StorageError
from app.storage.models import UploadRequest
from app.storage.providers.baidu_provider import BaiduPanProvider
from app.storage.providers.self_hosted_provider import SelfHostedPanProvider
from app.storage.self_hosted_categories import SELF_HOSTED_FILE_ARCH_CATEGORIES


def _cipher() -> Fernet:
    try:
        return Fernet(settings.baidu_token_encryption_key.encode())
    except (ValueError, TypeError) as exc:
        raise StorageError("NOT_CONFIGURED", "Set a valid BAIDU_TOKEN_ENCRYPTION_KEY") from exc


def save_oauth_account(db: Session, name: str, tokens: dict) -> StorageAccount:
    cipher = _cipher()
    account = db.scalar(select(StorageAccount).where(StorageAccount.provider == StorageProviderType.BAIDU,
                                                     StorageAccount.name == name))
    if account is None:
        account = StorageAccount(provider=StorageProviderType.BAIDU, name=name,
                                 encrypted_access_token="", encrypted_refresh_token="",
                                 expires_at=beijing_now())
        db.add(account)
    account.encrypted_access_token = cipher.encrypt(tokens["access_token"].encode()).decode()
    account.encrypted_refresh_token = cipher.encrypt(tokens["refresh_token"].encode()).decode()
    account.expires_at = beijing_now() + timedelta(seconds=max(60, int(tokens.get("expires_in", 2592000))))
    account.status = StorageAccountStatus.ACTIVE
    db.commit()
    db.refresh(account)
    return account


def access_token(db: Session, account: StorageAccount, provider: BaiduPanProvider) -> str:
    cipher = _cipher()
    try:
        if account.expires_at <= beijing_now() + timedelta(minutes=5):
            refresh = cipher.decrypt(account.encrypted_refresh_token.encode()).decode()
            try:
                tokens = provider.refresh_token(refresh)
            except StorageError:
                account.status = StorageAccountStatus.EXPIRED
                db.commit()
                raise
            save_oauth_account(db, account.name, tokens)
        return cipher.decrypt(account.encrypted_access_token.encode()).decode()
    except InvalidToken as exc:
        raise StorageError("TOKEN_DECRYPT_FAILED", "Baidu token encryption key does not match") from exc


def account_for_upload(db: Session, account_id: int | None = None) -> StorageAccount:
    query = select(StorageAccount).where(StorageAccount.provider == StorageProviderType.BAIDU,
                                         StorageAccount.status == StorageAccountStatus.ACTIVE)
    if account_id:
        query = query.where(StorageAccount.id == account_id)
    account = db.scalar(query.order_by(StorageAccount.id).limit(1))
    if account is None:
        raise StorageError("ACCOUNT_MISSING", "Connect an active Baidu account in Settings")
    return account


def archived_artifact(artifact: SoftwareArtifact, db: Session | None = None) -> Path:
    manager = ArchiveManager()
    local_exists = False
    if artifact.local_path:
        try:
            local_exists = manager.resolve_relative(artifact.local_path).is_file()
        except ValueError as exc:
            raise StorageError("INVALID_LOCAL_PATH", "Artifact archive path is unsafe") from exc
    if not local_exists and db is not None:
        staged = StagingManager().complete(artifact.id)
        if staged.is_file():
            variant = artifact.variant
            release = variant.release
            relative = manager.archive_relative(release.software.slug, release.version, variant.os.value,
                                                variant.architecture.value, artifact.filename)
            try:
                manager.archive(staged, relative)
            except FileExistsError:
                relative = relative.with_name(f"{relative.stem}-{time.time_ns()}{relative.suffix}")
                manager.archive(staged, relative)
            artifact.local_path = relative.as_posix()
            artifact.file_size = (manager.root / relative).stat().st_size
            artifact.download_status = DownloadStatus.DOWNLOADED
            local = db.scalar(select(ArtifactStorage).where(ArtifactStorage.artifact_id == artifact.id,
                ArtifactStorage.provider == StorageProviderType.LOCAL).limit(1))
            if local is None:
                local = ArtifactStorage(artifact_id=artifact.id, provider=StorageProviderType.LOCAL)
                db.add(local)
            local.remote_path = relative.as_posix()
            local.status = StorageStatus.AVAILABLE
            db.commit()
    if not artifact.local_path:
        raise StorageError("LOCAL_FILE_MISSING", "Artifact has no local archive path")
    try:
        path = ArchiveManager().resolve_relative(artifact.local_path)
    except ValueError as exc:
        raise StorageError("INVALID_LOCAL_PATH", "Artifact archive path is unsafe") from exc
    if not path.is_file():
        raise StorageError("LOCAL_FILE_MISSING", "Verified archive file is missing")
    return path


def queue_upload(db: Session, artifact_id: int, account_id: int | None = None) -> Job:
    artifact = db.get(SoftwareArtifact, artifact_id)
    if artifact is None:
        raise StorageError("NOT_FOUND", "Artifact not found")
    archived_artifact(artifact, db)
    account = account_for_upload(db, account_id)
    existing = db.scalar(select(ArtifactStorage).where(ArtifactStorage.artifact_id == artifact_id,
                    ArtifactStorage.provider == StorageProviderType.BAIDU).with_for_update())
    if existing and existing.upload_status == UploadStatus.SUCCESS:
        raise StorageError("ALREADY_UPLOADED", "This artifact already has a Baidu storage location")
    active = db.scalar(select(Job.id).where(Job.job_type.in_([JobType.UPLOAD_STORAGE, JobType.UPLOAD_BAIDU]),
                    Job.target_type == "artifact", Job.target_id == artifact_id,
                    Job.status.in_([JobStatus.PENDING, JobStatus.RUNNING])).limit(1))
    if active:
        raise StorageError("UPLOAD_IN_PROGRESS", "An upload job already exists for this artifact")
    folder = safe_component(settings.baidu_app_folder)
    if not folder:
        raise StorageError("NOT_CONFIGURED", "Set BAIDU_APP_FOLDER to the registered app folder")
    remote = f"/apps/{folder}/artifact-{artifact_id}-{safe_filename(artifact.filename)}"
    storage = existing or ArtifactStorage(artifact_id=artifact_id, provider=StorageProviderType.BAIDU)
    storage.remote_path = remote
    storage.account_id = account.id
    storage.remote_file_id = None
    storage.share_id = None
    storage.share_url = None
    storage.share_code = None
    storage.share_password = None
    storage.status = StorageStatus.PENDING
    storage.upload_status = UploadStatus.PENDING
    storage.share_status = ShareStatus.NONE
    db.add(storage)
    db.flush()
    job = Job(job_type=JobType.UPLOAD_STORAGE, target_type="artifact", target_id=artifact_id,
              status=JobStatus.PENDING, progress=0, message="Waiting for Baidu upload",
              payload={"storage_id": storage.id, "account_id": account.id, "provider": StorageProviderType.BAIDU.value})
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def queue_self_hosted_upload(db: Session, artifact_id: int, file_arch: str) -> Job:
    if not settings.self_hosted_api_key or not settings.self_hosted_username or not settings.self_hosted_base_url:
        raise StorageError("NOT_CONFIGURED", "Set SELF_HOSTED_BASE_URL, SELF_HOSTED_API_KEY and SELF_HOSTED_USERNAME")
    artifact = db.get(SoftwareArtifact, artifact_id)
    if artifact is None:
        raise StorageError("NOT_FOUND", "Artifact not found")
    archived_artifact(artifact, db)
    if file_arch not in SELF_HOSTED_FILE_ARCH_CATEGORIES:
        raise StorageError("INVALID_CATEGORY", "Select a valid cloud-drive file category")
    existing = db.scalar(select(ArtifactStorage).where(
        ArtifactStorage.artifact_id == artifact_id,
        ArtifactStorage.provider == StorageProviderType.SELF_HOSTED,
    ).with_for_update())
    if existing and existing.upload_status == UploadStatus.SUCCESS:
        raise StorageError("ALREADY_UPLOADED", "This artifact already has a cloud-drive location")
    active = db.scalar(select(Job.id).where(
        Job.job_type == JobType.UPLOAD_STORAGE,
        Job.target_type == "artifact", Job.target_id == artifact_id,
        Job.status.in_([JobStatus.PENDING, JobStatus.RUNNING]),
    ).limit(1))
    if active:
        raise StorageError("UPLOAD_IN_PROGRESS", "An upload job already exists for this artifact")
    storage = existing or ArtifactStorage(artifact_id=artifact_id, provider=StorageProviderType.SELF_HOSTED)
    storage.remote_path = None
    storage.remote_file_id = None
    storage.remote_parent_id = file_arch
    storage.share_id = None
    storage.share_url = None
    storage.share_code = None
    storage.share_password = None
    storage.status = StorageStatus.PENDING
    storage.upload_status = UploadStatus.PENDING
    storage.share_status = ShareStatus.NONE
    db.add(storage)
    db.flush()
    job = Job(
        job_type=JobType.UPLOAD_STORAGE, target_type="artifact", target_id=artifact_id,
        status=JobStatus.PENDING, progress=0, message="Waiting for self-hosted cloud upload",
        payload={"storage_id": storage.id, "provider": StorageProviderType.SELF_HOSTED.value,
                 "file_arch": file_arch},
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def run_upload(db: Session, job: Job, provider: BaiduPanProvider) -> None:
    artifact = db.get(SoftwareArtifact, job.target_id)
    storage = db.get(ArtifactStorage, (job.payload or {}).get("storage_id"))
    account = db.get(StorageAccount, (job.payload or {}).get("account_id"))
    if not artifact or not storage or not account:
        raise StorageError("NOT_FOUND", "Upload target, location or account is missing")
    path = archived_artifact(artifact, db)
    if not artifact.md5:
        artifact.md5 = SelfHostedPanProvider._md5(path)
        db.commit()
    variant = artifact.variant
    release = variant.release
    software = release.software
    token = access_token(db, account, provider)
    storage.status = StorageStatus.UPLOADING
    storage.upload_status = UploadStatus.UPLOADING
    db.commit()

    def progress(sent: int, total: int) -> None:
        job.progress = min(99, int(100 * sent / total))
        job.message = f"Uploaded {sent} / {total} bytes"
        job.result = {"bytes_uploaded": sent, "total_bytes": total}
        db.commit()

    result = provider.upload(UploadRequest(artifact.id, path, storage.remote_path, token, progress))
    storage.remote_path = result.remote_path
    storage.remote_file_id = result.remote_file_id
    storage.status = StorageStatus.AVAILABLE
    storage.upload_status = UploadStatus.SUCCESS
    job.result = {"storage_id": storage.id, "remote_file_id": result.remote_file_id,
                  "bytes_uploaded": result.size, "total_bytes": result.size}
    db.commit()


def run_self_hosted_upload(db: Session, job: Job, provider: SelfHostedPanProvider) -> None:
    artifact = db.get(SoftwareArtifact, job.target_id)
    storage = db.get(ArtifactStorage, (job.payload or {}).get("storage_id"))
    if not artifact or not storage:
        raise StorageError("NOT_FOUND", "Upload target or storage record is missing")
    path = archived_artifact(artifact, db)
    if not artifact.md5:
        artifact.md5 = SelfHostedPanProvider._md5(path)
        db.commit()
    variant = artifact.variant
    release = variant.release
    software = release.software
    file_arch = (job.payload or {}).get("file_arch")
    storage.status = StorageStatus.UPLOADING
    storage.upload_status = UploadStatus.UPLOADING
    db.commit()

    def progress(sent: int, total: int) -> None:
        job.progress = min(99, int(100 * sent / total)) if total else 0
        job.message = f"Uploaded {sent} / {total} bytes"
        job.result = {"bytes_uploaded": sent, "total_bytes": total}
        db.commit()

    result = provider.upload(UploadRequest(
        artifact_id=artifact.id, local_path=path, remote_path="", progress=progress,
        metadata={"filename": artifact.filename, "file_size": path.stat().st_size,
                  "file_arch": file_arch, "software_metadata": {
                      "md5": artifact.md5, "sha256": artifact.sha256, "version": release.version,
                      "origin_region": software.origin_region.value, "os": variant.os.value,
                      "architecture": variant.architecture.value, "cpu_family": variant.cpu_family.value,
                      "install_type": artifact.install_type.value, "language": variant.language or "UNKNOWN",
                  }},
    ))
    storage.remote_path = result.remote_path
    storage.remote_file_id = result.remote_file_id
    storage.remote_parent_id = file_arch
    storage.status = StorageStatus.AVAILABLE
    storage.upload_status = UploadStatus.SUCCESS
    job.result = {"storage_id": storage.id, "remote_file_id": result.remote_file_id,
                  "remote_path": result.remote_path, "file_arch": file_arch,
                  "bytes_uploaded": result.size, "total_bytes": result.size}
    db.commit()


def create_share(db: Session, storage: ArtifactStorage, password: str | None = None,
                 provider: BaiduPanProvider | None = None) -> ArtifactStorage:
    if storage.provider != StorageProviderType.BAIDU or storage.upload_status != UploadStatus.SUCCESS or not storage.remote_file_id:
        raise StorageError("NOT_UPLOADED", "Baidu upload must finish before sharing")
    if storage.share_status == ShareStatus.CREATED:
        raise StorageError("ALREADY_SHARED", "Disable the current share before creating another")
    account = account_for_upload(db, storage.account_id)
    api = provider or BaiduPanProvider()
    try:
        token = access_token(db, account, api)
        storage.share_status = ShareStatus.CREATING
        db.commit()
        result = api.create_share(storage.remote_file_id, token, password)
        storage.share_id = result.share_id
        storage.share_url = result.url
        storage.share_code = result.code
        storage.share_password = result.code
        storage.share_status = ShareStatus.CREATED
        db.commit()
        return storage
    except Exception:
        db.rollback()
        storage.share_status = ShareStatus.NONE
        db.commit()
        raise
    finally:
        if provider is None:
            api.close()


def disable_share(db: Session, storage: ArtifactStorage, provider: BaiduPanProvider | None = None) -> ArtifactStorage:
    if storage.provider != StorageProviderType.BAIDU or storage.share_status != ShareStatus.CREATED or not storage.share_id:
        raise StorageError("NOT_SHARED", "There is no active Baidu share")
    account = account_for_upload(db, storage.account_id)
    api = provider or BaiduPanProvider()
    try:
        api.remove_share(storage.share_id, access_token(db, account, api))
        storage.share_status = ShareStatus.DISABLED
        storage.share_url = None
        storage.share_code = None
        storage.share_password = None
        db.commit()
        return storage
    finally:
        if provider is None:
            api.close()
