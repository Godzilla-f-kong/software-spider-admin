from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, PlainSerializer

from app.core import enums as e
from app.db.base import BEIJING


def beijing_iso(value: datetime) -> str:
    return value.replace(tzinfo=BEIJING).isoformat() if value.tzinfo is None else value.astimezone(BEIJING).isoformat()


BeijingDateTime = Annotated[datetime, PlainSerializer(beijing_iso, return_type=str, when_used="json")]


class ReadBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: BeijingDateTime
    updated_at: BeijingDateTime


class CandidateWrite(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    normalized_name: str | None = Field(default=None, max_length=255)
    category: str | None = None
    source_platform: str | None = None
    source_url: str | None = None
    target_version: str | None = Field(default=None, max_length=100)
    target_os: e.OperatingSystem | None = None
    target_architecture: e.Architecture | None = None
    sales_signal: str | None = None
    search_signal: str | None = None
    competition_signal: str | None = None
    commercial_score: Decimal | None = Field(default=None, ge=0, le=100)
    seo_score: Decimal | None = Field(default=None, ge=0, le=100)
    brand_relevance_score: Decimal | None = Field(default=None, ge=0, le=100)
    priority_score: Decimal | None = Field(default=None, ge=0, le=100)
    status: e.CandidateStatus = e.CandidateStatus.DISCOVERED


class CandidateRead(ReadBase, CandidateWrite):
    normalized_name: str
    software_id: int | None


class CrawlPoolWrite(BaseModel):
    base_url: str = Field(min_length=10, max_length=2048)
    enabled: bool = True
    max_pages: int = Field(default=60, ge=1, le=200)
    max_depth: int = Field(default=2, ge=0, le=4)
    search_path_template: str | None = Field(default=None, max_length=1024)
    category_paths: str | None = Field(default=None, max_length=4000)


class CrawlPoolRead(ReadBase, CrawlPoolWrite):
    status: e.SourceStatus
    last_checked_at: BeijingDateTime | None
    last_error: str | None
    last_result_count: int


class SoftwareWrite(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=255, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    developer: str | None = None
    category: str | None = None
    license: str | None = None
    official_url: str | None = None
    summary: str | None = None
    description: str | None = None
    status: e.SoftwareStatus = e.SoftwareStatus.ACTIVE


class SoftwareRead(ReadBase, SoftwareWrite):
    latest_release: str | None = None


class SourceWrite(BaseModel):
    software_id: int
    source_type: e.SourceType
    source_url: str = Field(min_length=1)
    adapter_type: e.AdapterType = e.AdapterType.MANUAL
    priority: int = 100
    enabled: bool = True
    status: e.SourceStatus = e.SourceStatus.NEW
    automation_status: e.AutomationStatus = e.AutomationStatus.UNKNOWN


class SourceRead(ReadBase, SourceWrite):
    last_checked_at: BeijingDateTime | None
    last_success_at: BeijingDateTime | None
    last_error: str | None


class ReleaseWrite(BaseModel):
    software_id: int
    version: str = Field(min_length=1, max_length=100)
    release_date: date | None = None
    release_notes: str | None = None
    is_latest: bool = False
    status: e.ReleaseStatus = e.ReleaseStatus.DISCOVERED


class ReleaseRead(ReadBase, ReleaseWrite):
    pass


class VariantWrite(BaseModel):
    release_id: int
    os: e.OperatingSystem
    architecture: e.Architecture
    edition: str | None = None
    language: str | None = None
    min_os_version: str | None = None
    notes: str | None = None


class VariantRead(ReadBase, VariantWrite):
    pass


class ArtifactWrite(BaseModel):
    variant_id: int
    package_type: e.PackageType
    filename: str = Field(min_length=1, max_length=512)
    file_size: int | None = Field(default=None, ge=0)
    source_url: str | None = None
    local_path: str | None = None
    sha256: str | None = Field(default=None, min_length=64, max_length=64)
    md5: str | None = Field(default=None, min_length=32, max_length=32)
    signature_status: e.SignatureStatus = e.SignatureStatus.UNKNOWN
    verification_status: e.VerificationStatus = e.VerificationStatus.PENDING
    download_status: e.DownloadStatus = e.DownloadStatus.NOT_DOWNLOADED


class ArtifactRead(ReadBase, ArtifactWrite):
    resolved_url: str | None = None
    downloaded_at: BeijingDateTime | None = None
    verified_at: BeijingDateTime | None = None
    manual_reviewed_at: BeijingDateTime | None = None
    verification_details: dict[str, Any] | None = None
    redistribution_status: e.RedistributionStatus = e.RedistributionStatus.UNKNOWN


class DownloadLinkWrite(BaseModel):
    software_id: int
    source_id: int
    release_id: int | None = None
    provider: e.DownloadLinkProvider = e.DownloadLinkProvider.OTHER
    link_type: e.DownloadLinkType = e.DownloadLinkType.DOWNLOAD_PAGE
    link_url: str = Field(min_length=1, max_length=2048)
    source_page_url: str | None = Field(default=None, max_length=2048)
    access_code: str | None = Field(default=None, max_length=64)
    label: str | None = Field(default=None, max_length=255)
    context_text: str | None = None
    review_status: e.LinkReviewStatus = e.LinkReviewStatus.DISCOVERED


class DownloadLinkRead(ReadBase, DownloadLinkWrite):
    pass


class StorageWrite(BaseModel):
    artifact_id: int
    provider: e.StorageProviderType
    remote_path: str | None = None
    remote_file_id: str | None = None
    share_url: str | None = None
    share_code: str | None = None
    status: e.StorageStatus = e.StorageStatus.PENDING


class StorageRead(ReadBase, StorageWrite):
    account_id: int | None = None
    remote_parent_id: str | None = None
    share_password: str | None = None
    share_id: str | None = None
    upload_status: e.UploadStatus = e.UploadStatus.PENDING
    share_status: e.ShareStatus = e.ShareStatus.NONE


class ContentWrite(BaseModel):
    software_id: int
    release_id: int | None = None
    content_type: e.ContentType
    skill_name: str | None = None
    skill_version: str | None = None
    title: str | None = None
    content: str | None = None
    status: e.ContentStatus = e.ContentStatus.DRAFT


class ContentRead(ReadBase, ContentWrite):
    pass


class ListingWrite(BaseModel):
    software_id: int
    release_id: int | None = None
    platform: e.CommercePlatform
    generated_content_id: int | None = None
    title: str = Field(min_length=1)
    description: str | None = None
    price: Decimal | None = Field(default=None, ge=0)
    listing_url: str | None = None
    status: e.ListingStatus = e.ListingStatus.DRAFT


class ListingRead(ReadBase, ListingWrite):
    generated_at: BeijingDateTime | None
    reviewed_at: BeijingDateTime | None
    published_at: BeijingDateTime | None


class JobWrite(BaseModel):
    job_type: e.JobType
    target_type: str = Field(min_length=1, max_length=100)
    target_id: int = Field(gt=0)
    message: str | None = None
    payload: dict[str, Any] | None = None


class JobRead(ReadBase, JobWrite):
    status: e.JobStatus
    progress: int
    error_message: str | None
    result: dict[str, Any] | None
    started_at: BeijingDateTime | None
    finished_at: BeijingDateTime | None


class Page(BaseModel):
    items: list[dict[str, Any]]
    total: int
    page: int
    page_size: int
