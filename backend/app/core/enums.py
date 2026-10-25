from enum import Enum


class Choice(str, Enum):
    pass


class CandidateStatus(Choice):
    DISCOVERED = "DISCOVERED"
    REVIEWING = "REVIEWING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    IGNORED = "IGNORED"


class SoftwareStatus(Choice):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    ARCHIVED = "ARCHIVED"


class OriginRegion(Choice):
    DOMESTIC = "DOMESTIC"
    FOREIGN = "FOREIGN"
    UNKNOWN = "UNKNOWN"


class CpuFamily(Choice):
    AMD = "AMD"
    ARM = "ARM"
    UNKNOWN = "UNKNOWN"


class InstallType(Choice):
    PORTABLE = "PORTABLE"
    INSTALLER = "INSTALLER"
    UNKNOWN = "UNKNOWN"


class SourceType(Choice):
    OFFICIAL = "OFFICIAL"
    OFFICIAL_DOWNLOAD = "OFFICIAL_DOWNLOAD"
    GITHUB = "GITHUB"
    MIRROR = "MIRROR"
    OTHER = "OTHER"


class AdapterType(Choice):
    GENERIC_HTML = "GENERIC_HTML"
    GITHUB_RELEASE = "GITHUB_RELEASE"
    JSON_API = "JSON_API"
    STATIC_URL = "STATIC_URL"
    BROWSER = "BROWSER"
    MANUAL = "MANUAL"


class SourceStatus(Choice):
    NEW = "NEW"
    HEALTHY = "HEALTHY"
    FAILED = "FAILED"
    DISABLED = "DISABLED"


class AutomationStatus(Choice):
    UNKNOWN = "UNKNOWN"
    ALLOWED = "ALLOWED"
    MANUAL_REQUIRED = "MANUAL_REQUIRED"
    DISABLED = "DISABLED"


class ReleaseStatus(Choice):
    DISCOVERED = "DISCOVERED"
    PROCESSING = "PROCESSING"
    READY = "READY"
    PUBLISHED = "PUBLISHED"
    REJECTED = "REJECTED"


class OperatingSystem(Choice):
    WINDOWS = "WINDOWS"
    LINUX = "LINUX"
    MACOS = "MACOS"
    ANDROID = "ANDROID"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class Architecture(Choice):
    X86 = "X86"
    X64 = "X64"
    ARM = "ARM"
    ARM64 = "ARM64"
    UNIVERSAL = "UNIVERSAL"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class PackageType(Choice):
    EXE = "EXE"
    MSI = "MSI"
    ZIP = "ZIP"
    SEVEN_Z = "SEVEN_Z"
    TAR_GZ = "TAR_GZ"
    TAR_XZ = "TAR_XZ"
    DMG = "DMG"
    PKG = "PKG"
    DEB = "DEB"
    RPM = "RPM"
    APPIMAGE = "APPIMAGE"
    OTHER = "OTHER"


class DownloadStatus(Choice):
    NOT_DOWNLOADED = "NOT_DOWNLOADED"
    QUEUED = "QUEUED"
    DOWNLOADING = "DOWNLOADING"
    DOWNLOADED = "DOWNLOADED"
    FAILED = "FAILED"


class VerificationStatus(Choice):
    PENDING = "PENDING"
    VERIFYING = "VERIFYING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class SignatureStatus(Choice):
    UNKNOWN = "UNKNOWN"
    VALID = "VALID"
    INVALID = "INVALID"
    UNSIGNED = "UNSIGNED"


class RedistributionStatus(Choice):
    UNKNOWN = "UNKNOWN"
    ALLOWED = "ALLOWED"
    PROHIBITED = "PROHIBITED"


class StorageProviderType(Choice):
    LOCAL = "LOCAL"
    BAIDU = "BAIDU"
    PAN123 = "PAN123"
    SELF_HOSTED = "SELF_HOSTED"
    S3 = "S3"
    OTHER = "OTHER"


class StorageStatus(Choice):
    PENDING = "PENDING"
    UPLOADING = "UPLOADING"
    AVAILABLE = "AVAILABLE"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class UploadStatus(Choice):
    PENDING = "PENDING"
    UPLOADING = "UPLOADING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class ShareStatus(Choice):
    NONE = "NONE"
    CREATING = "CREATING"
    CREATED = "CREATED"
    EXPIRED = "EXPIRED"
    DISABLED = "DISABLED"


class StorageAccountStatus(Choice):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    DISABLED = "DISABLED"


class DownloadLinkProvider(Choice):
    QUARK = "QUARK"
    XUNLEI = "XUNLEI"
    BAIDU = "BAIDU"
    PAN123 = "PAN123"
    ALIYUN = "ALIYUN"
    LANZOU = "LANZOU"
    OTHER = "OTHER"


class DownloadLinkType(Choice):
    PAN_SHARE = "PAN_SHARE"
    DOWNLOAD_PAGE = "DOWNLOAD_PAGE"
    DIRECT_FILE = "DIRECT_FILE"


class LinkReviewStatus(Choice):
    DISCOVERED = "DISCOVERED"
    REVIEWED = "REVIEWED"
    IGNORED = "IGNORED"


class ContentType(Choice):
    WEBSITE = "WEBSITE"
    XIANYU = "XIANYU"
    TAOBAO = "TAOBAO"
    VERSION_NOTICE = "VERSION_NOTICE"


class ContentStatus(Choice):
    NOT_GENERATED = "NOT_GENERATED"
    GENERATING = "GENERATING"
    DRAFT = "DRAFT"
    REVIEWED = "REVIEWED"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"


class CommercePlatform(Choice):
    XIANYU = "XIANYU"
    TAOBAO = "TAOBAO"


class ListingStatus(Choice):
    DRAFT = "DRAFT"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"
    PAUSED = "PAUSED"
    REMOVED = "REMOVED"


class JobType(Choice):
    CRAWL = "CRAWL"
    CHECK_RELEASE = "CHECK_RELEASE"
    DOWNLOAD = "DOWNLOAD"
    VERIFY = "VERIFY"
    UPLOAD_BAIDU = "UPLOAD_BAIDU"
    UPLOAD_STORAGE = "UPLOAD_STORAGE"
    REGISTER_SHARE_LINK = "REGISTER_SHARE_LINK"
    GENERATE_WEBSITE = "GENERATE_WEBSITE"
    GENERATE_XIANYU = "GENERATE_XIANYU"
    GENERATE_TAOBAO = "GENERATE_TAOBAO"
    PUBLISH_WEBSITE = "PUBLISH_WEBSITE"


class ShareLinkSubmissionStatus(Choice):
    INCOMPLETE = "INCOMPLETE"
    READY = "READY"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class JobStatus(Choice):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
