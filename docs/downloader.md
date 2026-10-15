# Phase 3 direct downloader

The Admin creates one `DOWNLOAD` Job per `SoftwareArtifact`. A bounded Job runner calls `DownloadService`, which coordinates `HttpDownloader`, `StagingManager`, `VerificationService`, and `ArchiveManager`; the HTTP request returns immediately. The downloader streams HTTP/HTTPS bytes into `staging/jobs/{artifact_id}/artifact.part`. It validates the initial URL and every redirect using `DownloadPolicy` and the Spider URL safety validator. Public CDN redirects are permitted by default; `DOWNLOAD_ALLOWED_DOMAINS` and `DOWNLOAD_ALLOWED_REDIRECT_DOMAINS` can restrict hosts. Private, loopback, link-local and non-HTTP URLs are blocked by default. `ALLOW_PRIVATE_SOURCE_URLS=true` explicitly enables private sources for both Spider and Downloader.

## Lifecycle

`DOWNLOAD` progresses `PENDING → RUNNING → SUCCESS/FAILED/CANCELLED`. A successful download becomes `.downloaded`, updates the Artifact to `DOWNLOADED`, and creates a `VERIFY` Job. `VERIFY` calculates SHA256 and MD5, checks magic bytes, ZIP CRC or TAR structure where supported, reads PE machine and version resources, and checks Authenticode on Windows. Its structured checks are stored in `software_artifacts.verification_details` and the Job result. HTML error pages and corrupt archives are rejected. Uncertain OS, architecture, version, and unsupported deep checks cause `MANUAL_REVIEW`. A reviewer may approve or reject with confirmation.

Only `VERIFIED` files move to `archive/{software_slug}/{version}/{os}/{architecture}/{filename}`. `REJECTED` staged files move to `failed/`. The database stores `local_path` relative to `DATA_ROOT`, not an absolute host path. Re-download preserves the previous archive; changed SHA256 requires manual review. `redistribution_status` starts `UNKNOWN` and local verification does not grant distribution permission.

## Resume, retry, and cancellation

A surviving `.part` causes a `Range` request. A valid `206 Content-Range` appends; a `200` truncates and restarts. Connection and timeout failures leave `.part` in place. Cancellation is checked in the chunk loop and leaves `.part` for a later retry. Startup marks interrupted `RUNNING` Jobs failed and requeues pending jobs. Retryable network errors and 5xx/429 are retried up to `DOWNLOAD_MAX_RETRIES`; 401/403/404 are not retried. Jobs report bytes, total (if known), and average speed in `result`; without a length the percentage remains indeterminate.

## Configuration

Configure in `.env`: `DATA_ROOT`, `DOWNLOAD_TIMEOUT`, `DOWNLOAD_CONNECT_TIMEOUT`, `DOWNLOAD_MAX_RETRIES`, `DOWNLOAD_CHUNK_SIZE`, `DOWNLOAD_MAX_CONCURRENCY`, `DOWNLOAD_USER_AGENT`, `DOWNLOAD_MAX_FILE_SIZE` (default 8 GiB; 0 means unlimited), `DOWNLOAD_MIN_FREE_SPACE`, `DOWNLOAD_ALLOWED_DOMAINS`, and `DOWNLOAD_ALLOWED_REDIRECT_DOMAINS`. Download settings require a backend restart. Current default data root is `F:/software_spider_bak` when `.env` is configured that way. Use `pathlib` paths on Windows.

## API

`POST /api/v1/artifacts/{id}/download`, `/redownload`, `/verify`, `/review/approve`, `/review/reject`; `POST /api/v1/jobs/{id}/cancel`; `POST /api/v1/downloads/bulk` with an array of Artifact IDs. Read Artifact and Job details using existing CRUD endpoints. Never pass arbitrary filesystem paths through an API.

## Extending verification

Add a check to `VerificationService.verify` and return a named PASS/WARNING/FAIL entry. Treat uncertain metadata as warning, and only accept a file automatically when the available evidence supports its declared format, version and architecture. A future malware scanner or storage provider should be a separate service after verification. Cloud share links in `download_links` are not direct Artifact URLs and are not downloaded by this module.

## Known limits

MSI product metadata, 7Z deep integrity and some platform specific packages require manual review. PowerShell signature status is a signal, not proof of safety. A DNS change between validation and connection is not pinned at the socket layer, so use a restrictive egress firewall for deployments with untrusted administrators. This local single-process executor is not a distributed queue; run one backend worker until a durable queue is introduced.
