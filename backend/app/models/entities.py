from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Enum as SqlEnum, ForeignKey, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core import enums as e
from app.db.base import Base, TimestampMixin


def enum_column(enum_type: type[e.Choice], default: e.Choice | None = None):
    from sqlalchemy import Enum as SqlEnum

    return mapped_column(SqlEnum(enum_type, native_enum=False, length=32), default=default, nullable=False)


class SoftwareCandidate(TimestampMixin, Base):
    __tablename__ = "software_candidates"
    __table_args__ = {"comment": "候选软件 / Discovered software candidates"}
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255))
    normalized_name: Mapped[str] = mapped_column(String(255), index=True)
    category: Mapped[str | None] = mapped_column(String(100))
    source_platform: Mapped[str | None] = mapped_column(String(100))
    source_url: Mapped[str | None] = mapped_column(String(2048))
    target_version: Mapped[str | None] = mapped_column(String(100), comment="目标软件版本 / Target version")
    target_os: Mapped[e.OperatingSystem | None] = mapped_column(
        SqlEnum(e.OperatingSystem, native_enum=False, length=32), nullable=True,
        comment="目标操作系统 / Target OS")
    target_architecture: Mapped[e.Architecture | None] = mapped_column(
        SqlEnum(e.Architecture, native_enum=False, length=32), nullable=True,
        comment="目标 CPU 架构 / Target CPU architecture")
    sales_signal: Mapped[str | None] = mapped_column(Text)
    search_signal: Mapped[str | None] = mapped_column(Text)
    competition_signal: Mapped[str | None] = mapped_column(Text)
    commercial_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    seo_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    brand_relevance_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    priority_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    status: Mapped[e.CandidateStatus] = enum_column(e.CandidateStatus, e.CandidateStatus.DISCOVERED)
    software_id: Mapped[int | None] = mapped_column(ForeignKey("software.id", ondelete="RESTRICT"), index=True)


class CrawlPool(TimestampMixin, Base):
    """A user supplied website entry point, independent of any software."""
    __tablename__ = "crawl_pools"
    __table_args__ = {"comment": "人工维护的网站主页抓取池 / User managed website crawl pool"}
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    base_url: Mapped[str] = mapped_column(String(2048))
    url_hash: Mapped[str] = mapped_column(String(64), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    max_pages: Mapped[int] = mapped_column(Integer, default=60)
    max_depth: Mapped[int] = mapped_column(Integer, default=2)
    search_path_template: Mapped[str | None] = mapped_column(String(1024), comment="可选站内搜索路径模板，使用 {query} / Optional site search path")
    category_paths: Mapped[str | None] = mapped_column(Text, comment="可选分类路径，每行一个 / Optional category paths")
    status: Mapped[e.SourceStatus] = enum_column(e.SourceStatus, e.SourceStatus.NEW)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
    last_result_count: Mapped[int] = mapped_column(Integer, default=0)


class Software(TimestampMixin, Base):
    __tablename__ = "software"
    __table_args__ = {"comment": "软件产品 / Software products"}
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    slug: Mapped[str] = mapped_column(String(255), unique=True)
    developer: Mapped[str | None] = mapped_column(String(255))
    category: Mapped[str | None] = mapped_column(String(100), index=True)
    license: Mapped[str | None] = mapped_column(String(100))
    official_url: Mapped[str | None] = mapped_column(String(2048))
    summary: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[e.SoftwareStatus] = enum_column(e.SoftwareStatus, e.SoftwareStatus.ACTIVE)
    releases: Mapped[list["SoftwareRelease"]] = relationship(back_populates="software")
    sources: Mapped[list["SoftwareSource"]] = relationship(back_populates="software")


class SoftwareSource(TimestampMixin, Base):
    __tablename__ = "software_sources"
    __table_args__ = (Index("ix_sources_software_enabled", "software_id", "enabled"), {"comment": "软件来源 / Software sources"})
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    software_id: Mapped[int] = mapped_column(ForeignKey("software.id", ondelete="RESTRICT"), index=True)
    source_type: Mapped[e.SourceType] = enum_column(e.SourceType)
    source_url: Mapped[str] = mapped_column(String(2048))
    adapter_type: Mapped[e.AdapterType] = enum_column(e.AdapterType, e.AdapterType.MANUAL)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[e.SourceStatus] = enum_column(e.SourceStatus, e.SourceStatus.NEW)
    automation_status: Mapped[e.AutomationStatus] = enum_column(e.AutomationStatus, e.AutomationStatus.UNKNOWN)
    last_error: Mapped[str | None] = mapped_column(Text)
    software: Mapped[Software] = relationship(back_populates="sources")


class SoftwareRelease(TimestampMixin, Base):
    __tablename__ = "software_releases"
    __table_args__ = (UniqueConstraint("software_id", "version", name="uq_release_software_version"), {"comment": "软件版本 / Software releases"})
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    software_id: Mapped[int] = mapped_column(ForeignKey("software.id", ondelete="RESTRICT"), index=True)
    version: Mapped[str] = mapped_column(String(100))
    release_date: Mapped[date | None] = mapped_column(Date)
    release_notes: Mapped[str | None] = mapped_column(Text)
    is_latest: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[e.ReleaseStatus] = enum_column(e.ReleaseStatus, e.ReleaseStatus.DISCOVERED)
    software: Mapped[Software] = relationship(back_populates="releases")
    variants: Mapped[list["SoftwareVariant"]] = relationship(back_populates="release")


class SoftwareVariant(TimestampMixin, Base):
    __tablename__ = "software_variants"
    __table_args__ = {"comment": "运行环境变体 / Release variants"}
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("software_releases.id", ondelete="RESTRICT"), index=True)
    os: Mapped[e.OperatingSystem] = enum_column(e.OperatingSystem)
    architecture: Mapped[e.Architecture] = enum_column(e.Architecture)
    edition: Mapped[str | None] = mapped_column(String(100))
    language: Mapped[str | None] = mapped_column(String(50))
    min_os_version: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(Text)
    release: Mapped[SoftwareRelease] = relationship(back_populates="variants")
    artifacts: Mapped[list["SoftwareArtifact"]] = relationship(back_populates="variant")


class SoftwareArtifact(TimestampMixin, Base):
    __tablename__ = "software_artifacts"
    __table_args__ = {"comment": "软件安装文件 / Software artifacts"}
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    variant_id: Mapped[int] = mapped_column(ForeignKey("software_variants.id", ondelete="RESTRICT"), index=True)
    package_type: Mapped[e.PackageType] = enum_column(e.PackageType)
    filename: Mapped[str] = mapped_column(String(512))
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    source_url: Mapped[str | None] = mapped_column(String(2048))
    local_path: Mapped[str | None] = mapped_column(String(2048))
    resolved_url: Mapped[str | None] = mapped_column(String(2048))
    sha256: Mapped[str | None] = mapped_column(String(64))
    md5: Mapped[str | None] = mapped_column(String(32))
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    manual_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    verification_details: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    redistribution_status: Mapped[e.RedistributionStatus] = enum_column(e.RedistributionStatus, e.RedistributionStatus.UNKNOWN)
    signature_status: Mapped[e.SignatureStatus] = enum_column(e.SignatureStatus, e.SignatureStatus.UNKNOWN)
    verification_status: Mapped[e.VerificationStatus] = enum_column(e.VerificationStatus, e.VerificationStatus.PENDING)
    download_status: Mapped[e.DownloadStatus] = enum_column(e.DownloadStatus, e.DownloadStatus.NOT_DOWNLOADED)
    variant: Mapped[SoftwareVariant] = relationship(back_populates="artifacts")
    storage_locations: Mapped[list["ArtifactStorage"]] = relationship(back_populates="artifact")


class DownloadLink(TimestampMixin, Base):
    __tablename__ = "download_links"
    __table_args__ = (Index("ix_download_links_source_release", "source_id", "release_id"),
                      {"comment": "发现的下载入口和网盘分享 / Discovered download and cloud-share links"})
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    software_id: Mapped[int] = mapped_column(ForeignKey("software.id", ondelete="RESTRICT"), index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("software_sources.id", ondelete="RESTRICT"), index=True)
    release_id: Mapped[int | None] = mapped_column(ForeignKey("software_releases.id", ondelete="RESTRICT"), index=True)
    provider: Mapped[e.DownloadLinkProvider] = enum_column(e.DownloadLinkProvider, e.DownloadLinkProvider.OTHER)
    link_type: Mapped[e.DownloadLinkType] = enum_column(e.DownloadLinkType)
    link_url: Mapped[str] = mapped_column(String(2048))
    source_page_url: Mapped[str | None] = mapped_column(String(2048))
    access_code: Mapped[str | None] = mapped_column(String(64))
    label: Mapped[str | None] = mapped_column(String(255))
    context_text: Mapped[str | None] = mapped_column(Text)
    review_status: Mapped[e.LinkReviewStatus] = enum_column(e.LinkReviewStatus, e.LinkReviewStatus.DISCOVERED)


class ArtifactStorage(TimestampMixin, Base):
    __tablename__ = "artifact_storage"
    __table_args__ = {"comment": "文件存储位置 / Artifact storage locations"}
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    artifact_id: Mapped[int] = mapped_column(ForeignKey("software_artifacts.id", ondelete="RESTRICT"), index=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("storage_accounts.id", ondelete="RESTRICT"), index=True)
    provider: Mapped[e.StorageProviderType] = enum_column(e.StorageProviderType)
    remote_path: Mapped[str | None] = mapped_column(String(2048))
    remote_file_id: Mapped[str | None] = mapped_column(String(255))
    remote_parent_id: Mapped[str | None] = mapped_column(String(255))
    share_url: Mapped[str | None] = mapped_column(String(2048))
    share_code: Mapped[str | None] = mapped_column(String(100))
    share_password: Mapped[str | None] = mapped_column(String(100))
    share_id: Mapped[str | None] = mapped_column(String(255))
    upload_status: Mapped[e.UploadStatus] = enum_column(e.UploadStatus, e.UploadStatus.PENDING)
    share_status: Mapped[e.ShareStatus] = enum_column(e.ShareStatus, e.ShareStatus.NONE)
    status: Mapped[e.StorageStatus] = enum_column(e.StorageStatus, e.StorageStatus.PENDING)
    artifact: Mapped[SoftwareArtifact] = relationship(back_populates="storage_locations")


class StorageAccount(TimestampMixin, Base):
    __tablename__ = "storage_accounts"
    __table_args__ = (Index("uq_storage_accounts_provider_name", "provider", "name", unique=True),
                      {"comment": "加密存储的云存储授权 / Encrypted provider credentials"})
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider: Mapped[e.StorageProviderType] = enum_column(e.StorageProviderType)
    name: Mapped[str] = mapped_column(String(100))
    encrypted_access_token: Mapped[str] = mapped_column(Text)
    encrypted_refresh_token: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[e.StorageAccountStatus] = enum_column(e.StorageAccountStatus, e.StorageAccountStatus.ACTIVE)


class GeneratedContent(TimestampMixin, Base):
    __tablename__ = "generated_content"
    __table_args__ = {"comment": "生成内容草稿 / Generated content drafts"}
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    software_id: Mapped[int] = mapped_column(ForeignKey("software.id", ondelete="RESTRICT"), index=True)
    release_id: Mapped[int | None] = mapped_column(ForeignKey("software_releases.id", ondelete="RESTRICT"), index=True)
    content_type: Mapped[e.ContentType] = enum_column(e.ContentType)
    skill_name: Mapped[str | None] = mapped_column(String(100))
    skill_version: Mapped[str | None] = mapped_column(String(50))
    title: Mapped[str | None] = mapped_column(String(512))
    content: Mapped[str | None] = mapped_column(Text)
    status: Mapped[e.ContentStatus] = enum_column(e.ContentStatus, e.ContentStatus.DRAFT)


class CommerceListing(TimestampMixin, Base):
    __tablename__ = "commerce_listings"
    __table_args__ = {"comment": "电商商品文案 / Commerce listings"}
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    software_id: Mapped[int] = mapped_column(ForeignKey("software.id", ondelete="RESTRICT"), index=True)
    release_id: Mapped[int | None] = mapped_column(ForeignKey("software_releases.id", ondelete="RESTRICT"), index=True)
    platform: Mapped[e.CommercePlatform] = enum_column(e.CommercePlatform)
    generated_content_id: Mapped[int | None] = mapped_column(ForeignKey("generated_content.id", ondelete="RESTRICT"), index=True)
    title: Mapped[str] = mapped_column(String(512))
    description: Mapped[str | None] = mapped_column(Text)
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    listing_url: Mapped[str | None] = mapped_column(String(2048))
    status: Mapped[e.ListingStatus] = enum_column(e.ListingStatus, e.ListingStatus.DRAFT)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)


class Job(TimestampMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_status_created", "status", "created_at"), {"comment": "后台任务 / Background jobs"})
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_type: Mapped[e.JobType] = enum_column(e.JobType)
    target_type: Mapped[str] = mapped_column(String(100))
    target_id: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[e.JobStatus] = enum_column(e.JobStatus, e.JobStatus.PENDING)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(String(1024))
    error_message: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class SystemSetting(TimestampMixin, Base):
    __tablename__ = "system_settings"
    __table_args__ = {"comment": "Editable non-secret system settings"}
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


# Kept centrally so the same field has the same explanation across tables.
# Alembic compares these metadata comments with the live MySQL schema.
COLUMN_COMMENTS = {
    "id": "主键 ID / Primary key",
    "created_at": "创建时间（北京时间）/ Created at Asia/Shanghai",
    "updated_at": "更新时间（北京时间）/ Updated at Asia/Shanghai",
    "name": "名称 / Name",
    "normalized_name": "规范化名称 / Normalized name",
    "category": "分类 / Category",
    "source_platform": "发现平台 / Discovery platform",
    "source_url": "来源链接 / Source URL",
    "sales_signal": "销售线索 / Sales signal",
    "search_signal": "搜索线索 / Search signal",
    "competition_signal": "竞争线索 / Competition signal",
    "commercial_score": "商业评分 / Commercial score",
    "seo_score": "SEO 评分 / SEO score",
    "brand_relevance_score": "品牌相关评分 / Brand relevance score",
    "priority_score": "优先级评分 / Priority score",
    "status": "当前状态 / Status",
    "software_id": "关联软件 ID / Software ID",
    "slug": "唯一 URL 标识 / Unique URL slug",
    "developer": "开发者 / Developer",
    "license": "许可证 / License",
    "official_url": "官方网站 / Official website URL",
    "summary": "软件摘要 / Summary",
    "description": "详细描述 / Description",
    "source_type": "来源类型 / Source type",
    "adapter_type": "适配器类型 / Adapter type",
    "priority": "来源优先级 / Source priority",
    "enabled": "是否启用 / Enabled",
    "last_checked_at": "上次检查时间（北京时间）/ Last checked at Asia/Shanghai",
    "last_success_at": "上次成功时间（北京时间）/ Last success at Asia/Shanghai",
    "version": "版本号 / Version",
    "release_date": "发布日期 / Release date",
    "release_notes": "版本说明 / Release notes",
    "is_latest": "是否最新版本 / Is latest release",
    "release_id": "关联版本 ID / Release ID",
    "os": "操作系统 / Operating system",
    "architecture": "CPU 架构 / CPU architecture",
    "edition": "软件版本类型 / Edition",
    "language": "语言 / Language",
    "min_os_version": "最低操作系统版本 / Minimum OS version",
    "notes": "备注 / Notes",
    "variant_id": "关联运行环境 ID / Variant ID",
    "package_type": "安装包类型 / Package type",
    "filename": "文件名 / Filename",
    "file_size": "文件大小（字节）/ File size in bytes",
    "local_path": "本地文件路径 / Local file path",
    "sha256": "SHA-256 校验值 / SHA-256 checksum",
    "md5": "MD5 校验值 / MD5 checksum",
    "signature_status": "签名状态 / Signature status",
    "verification_status": "文件验证状态 / Verification status",
    "download_status": "下载状态 / Download status",
    "artifact_id": "关联文件 ID / Artifact ID",
    "provider": "存储提供方 / Storage provider",
    "remote_path": "远程文件路径 / Remote file path",
    "remote_file_id": "远程文件 ID / Remote file ID",
    "share_url": "分享链接 / Share URL",
    "share_code": "分享提取码 / Share code",
    "content_type": "内容类型 / Content type",
    "skill_name": "生成 Skill 名称 / Generator skill name",
    "skill_version": "生成 Skill 版本 / Generator skill version",
    "title": "标题 / Title",
    "content": "内容正文 / Content body",
    "platform": "电商平台 / Commerce platform",
    "generated_content_id": "关联生成内容 ID / Generated content ID",
    "price": "商品价格 / Price",
    "listing_url": "商品链接 / Listing URL",
    "generated_at": "生成时间（北京时间）/ Generated at Asia/Shanghai",
    "reviewed_at": "审核时间（北京时间）/ Reviewed at Asia/Shanghai",
    "published_at": "发布时间（北京时间）/ Published at Asia/Shanghai",
    "job_type": "任务类型 / Job type",
    "target_type": "目标实体类型 / Target entity type",
    "target_id": "目标实体 ID / Target entity ID",
    "progress": "进度百分比（0-100）/ Progress percent",
    "message": "任务消息 / Job message",
    "error_message": "错误信息 / Error message",
    "payload": "任务输入 JSON / Input JSON",
    "result": "任务结果 JSON / Result JSON",
    "started_at": "开始时间（北京时间）/ Started at Asia/Shanghai",
    "finished_at": "完成时间（北京时间）/ Finished at Asia/Shanghai",
}

COLUMN_COMMENTS["automation_status"] = "自动访问状态 / Automation status"
COLUMN_COMMENTS["last_error"] = "最近抓取错误 / Latest discovery error"
COLUMN_COMMENTS["source_id"] = "来源记录 ID / Source ID"
COLUMN_COMMENTS["link_type"] = "下载入口类型 / Link type"
COLUMN_COMMENTS["link_url"] = "网盘分享或下载入口 URL / Share or download URL"
COLUMN_COMMENTS["source_page_url"] = "发现该链接的页面 URL / Source page URL"
COLUMN_COMMENTS["access_code"] = "页面提供的访问码 / Access code shown on page"
COLUMN_COMMENTS["label"] = "链接显示文字 / Link label"
COLUMN_COMMENTS["context_text"] = "链接所在段落文字 / Surrounding paragraph text"
COLUMN_COMMENTS["review_status"] = "人工审核状态 / Human review status"
for _key, _comment in {
    "base_url": "人工录入的网站主页 / User supplied website home URL",
    "url_hash": "标准化主页 URL 的 SHA-256 / Normalized home URL SHA-256",
    "max_pages": "单次扫描最多访问页面数 / Maximum pages per scan",
    "max_depth": "站内链接最大遍历深度 / Maximum internal link depth",
    "last_result_count": "最近一次匹配候选数 / Matches in latest scan",
    "search_path_template": "可选站内搜索路径模板，使用 {query} / Optional site search path",
    "category_paths": "可选分类路径，每行一个 / Optional category paths",
    "target_version": "目标软件版本 / Target version",
    "target_os": "目标操作系统 / Target OS",
    "target_architecture": "目标 CPU 架构 / Target CPU architecture",
}.items():
    COLUMN_COMMENTS[_key] = _comment

for _field in ("created_at", "updated_at", "last_checked_at", "last_success_at",
               "started_at", "finished_at", "generated_at", "reviewed_at", "published_at"):
    COLUMN_COMMENTS[_field] = f"{_field.replace('_', ' ').title()} (Asia/Shanghai, UTC+08:00)"
COLUMN_COMMENTS["data"] = "Non-secret editable settings JSON"
for _key, _comment in {
    "account_id": "Storage account ID / 存储账号 ID",
    "remote_parent_id": "Remote parent directory ID / 远程父目录 ID",
    "share_password": "Share extraction password / 分享提取密码",
    "share_id": "Provider share ID / 网盘分享 ID",
    "upload_status": "Upload lifecycle / 上传状态",
    "share_status": "Share lifecycle / 分享状态",
    "encrypted_access_token": "Encrypted OAuth access token / 加密访问令牌",
    "encrypted_refresh_token": "Encrypted OAuth refresh token / 加密刷新令牌",
    "expires_at": "Token expiry in Beijing time / 北京时间到期",
}.items():
    COLUMN_COMMENTS[_key] = _comment
for _key, _comment in {
    "resolved_url": "Final validated download URL after redirects",
    "downloaded_at": "Downloaded at Asia/Shanghai",
    "verified_at": "Verified at Asia/Shanghai",
    "manual_reviewed_at": "Manually reviewed at Asia/Shanghai",
    "verification_details": "Structured verification checks and metadata JSON",
    "redistribution_status": "Permission to redistribute the artifact",
}.items():
    COLUMN_COMMENTS[_key] = _comment

for table in Base.metadata.tables.values():
    for column in table.columns:
        column.comment = COLUMN_COMMENTS[column.name]

Base.metadata.tables["download_links"].columns["provider"].comment = "链接所属平台 / Link provider"
for _key, _comment in {
    "id": "Account ID / 账号 ID",
    "provider": "Storage provider / 存储服务商",
    "name": "Account display name / 账号显示名",
    "status": "Account status / 账号状态",
    "created_at": "Created at Beijing time / 北京时间创建",
    "updated_at": "Updated at Beijing time / 北京时间更新",
}.items():
    Base.metadata.tables["storage_accounts"].columns[_key].comment = _comment

_download_links = Base.metadata.tables["download_links"]
_download_links.comment = "Discovered cloud share and download entry links"
for _name, _comment in {
    "id": "Primary key", "software_id": "Software ID", "source_id": "Source ID",
    "release_id": "Optional release ID", "provider": "Cloud or download provider",
    "link_type": "Share or download entry type", "link_url": "Discovered link URL",
    "source_page_url": "Page where the link was found", "access_code": "Access code shown on source page",
    "label": "Link label on page", "context_text": "Nearby source page text",
    "review_status": "Human review status", "created_at": "Created At (Asia/Shanghai, UTC+08:00)",
    "updated_at": "Updated At (Asia/Shanghai, UTC+08:00)",
}.items():
    _download_links.columns[_name].comment = _comment

for _field in ("created_at", "updated_at"):
    _download_links.columns[_field].comment = COLUMN_COMMENTS[_field]

Base.metadata.tables["system_settings"].columns["id"].comment = "Primary key"
