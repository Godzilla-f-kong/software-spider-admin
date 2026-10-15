# Spider architecture

## Independent website crawl pool

`CrawlPool` stores a user supplied website home URL and scan limits. It has no `software_id`. Administrators also enter `SoftwareCandidate` records manually; the crawler never invents or inserts candidates. `POST /api/v1/crawl-pools/{id}/scan` creates a `CRAWL` Job with `target_type=crawl_pool`. `PoolCrawler` follows same-site HTML links up to the configured page/depth limits, gives links mentioning candidate names priority, honors `robots.txt`, and matches candidates against the destination page's title or H1. It uses the shared `SpiderHttpClient` URL safety guard and request limits.

The Job result records matched candidate IDs, page URLs, versions, artifact counts and link counts. A homepage teaser alone is not considered a match. `POST /api/v1/crawl-pools/{pool_id}/scans/{job_id}/create-source` accepts a matched candidate/page pair from that successful Job only after the candidate has been accepted. It creates or reuses a `SoftwareSource` for the accepted software. From there, the existing source preview/import flow applies. This makes the URL pool independent from both candidate records and software-specific release sources; creating a source is an explicit review step.

The Admin has separate **Software Candidate Pool**, **URL Crawl Pool**, and **Catalog Software Sources** pages. A scan result remains visible through its Job ID. Link traversal stays on the configured site; a cross-site redirect is discarded after the shared HTTP client's safety checks. The crawler does not use JavaScript rendering and does not try to bypass login, robots restrictions, or access controls. A bounded scan can miss pages beyond its depth/page budget; increase the per-pool limits deliberately when needed.

Phase 2 discovers release metadata and installer URLs. It does not download installer bodies.

## Lifecycle

1. Admin creates an enabled `SoftwareSource` with an adapter type.
2. `POST /api/v1/sources/{id}/discover/preview` creates a `CRAWL` Job. The bounded spider executor runs it outside the HTTP request.
3. `SpiderService` selects an adapter through `SourceAdapterFactory`. The adapter uses `SpiderHttpClient` and returns a `DiscoveryResult`; it never writes catalog tables.
4. The preview is saved in `Job.result.discovery`. `DiscoveryPersistenceService.annotate` labels each candidate `NEW`, `EXISTING`, or `UNKNOWN`.
5. Admin reviews the preview and calls `POST /api/v1/sources/{id}/discover/import` with `{"preview_job_id": 123, "version_overrides": {"0": "1.2.3"}}`. Overrides are optional and let a reviewer supply an unknown version by its preview index. A second Job imports the stored result. Releases still lacking a version are skipped. Repeated imports reuse matching Release, Variant and Artifact records.

## Result structure

`DiscoveryResult` contains `source_id`, `software_id`, `software_metadata`, `source_metadata`, `warnings`, `errors`, and `releases`. Each `ReleaseCandidate` contains a raw and normalized version, date, prerelease flag, release URL and artifacts. Its computed `variants` group artifacts by OS, architecture, edition and language. Each `ArtifactCandidate` contains a filename, original/resolved/download URL, size, content type, OS, architecture, package type, optional edition and language. Unknown OS and architecture are stored explicitly; they are never guessed from `win32` alone.

The `VersionParser`, `URLNormalizer`, `URLSafetyValidator`, and `ArtifactClassifier` are shared by adapters. The normalizer preserves query parameters. URL validation blocks non-HTTP schemes and private or local addresses unless `ALLOW_PRIVATE_SOURCE_URLS=true` is intentionally configured. Redirect targets are checked again. The HTTP client limits response bodies, timeouts, retries and request rate. HTML/static sources consult `robots.txt` and mark denied sources for manual review.

## Adapters

- `GITHUB_RELEASE`: GitHub Releases API, public access by default; optional `GITHUB_TOKEN`. Draft releases are skipped.
- `GENERIC_HTML`: extracts installer links and cloud share/download entry links from an HTML page. It reads access codes from the same link paragraph or URL query. It does not open cloud shares or fetch full installers.

### Cloud share and download entry links

`GENERIC_HTML` treats cloud shares as a primary discovery result. The adapter recognizes Quark, Xunlei, Baidu Pan, 123Pan, Aliyun Drive, and Lanzou domains. It also keeps external download entries found under a page's download heading. Each entry includes provider, URL, source page, nearby text, and any unambiguous access code. Query parameters are retained. The adapter does not log in to cloud services, bypass access checks, or resolve share contents.

`DownloadLink` is stored separately from `SoftwareArtifact` and `ArtifactStorage`. A share link is an entry to a possibly unknown file collection; it is not proof of a particular installer. Preview and import work even if the page has no reliable version. In that case `release_id` is empty and the link remains attached to Software and Source for review. Repeated imports reuse matching source/release/URL records. Admin shows these records under **Cloud shares and download links** and in Software Detail.
- `STATIC_URL`: HEAD metadata for a direct installer URL. The stable original URL is persisted; a redirected CDN URL appears in preview metadata.
- `JSON_API`: basic `{ "releases": [{ "version": "1.2.3", "assets": [{ "url": "...", "filename": "..." }] }] }` format.
- `BROWSER`, `MANUAL`: interfaces that return `MANUAL_REQUIRED`; no browser automation in Phase 2.

To add a vendor adapter, implement `BaseSourceAdapter.discover(SourceInput) -> DiscoveryResult`, use the shared HTTP client and classifier, register the class in `SourceAdapterFactory.REGISTRY`, and add mocked response fixtures and tests. Keep vendor parsing out of persistence and API controllers.

## Release checks and jobs

Candidate pool automation creates one resumable `CRAWL` Job per eligible candidate. Each job checks its snapshotted enabled URL pools in order, continuing through per-request page budgets from a checkpoint. The first confirmed `MATCHED` resource ends that candidate job; the serial worker then starts the next queued candidate. Candidate priority score determines initial queue order. Existing active candidates are queued on backend startup, and adding or enabling a URL pool schedules that pool for candidates that have not already found a match. Results and the current site are visible in the candidate row and Job Detail. No matching resource after checking all sites is a completed job with a visible no-match result.

Spider jobs run with a fixed process-local concurrency of one. This includes automatic candidate searches, URL-pool scans, source discovery and release checks. The Admin deployment is single-process; running multiple independent backend processes would create separate in-memory worker queues and is not supported for the serial guarantee.

`POST /api/v1/software/{id}/check-release` selects the lowest-priority-number enabled automated source. `POST /api/v1/software/check-releases` accepts up to 50 software IDs. Both create `CHECK_RELEASE` Jobs on the same serial worker. Exact version equality means `NO_CHANGE`. A newer release date can mean `NEW_RELEASE`. When a safe comparison is unavailable, the result is `UNKNOWN` and needs review.

Jobs record progress, result or a typed error. Failed access updates `SoftwareSource.last_error`; denied sources become `MANUAL_REQUIRED`. This executor is process-local and has no durable queue recovery. Pending/running jobs interrupted by a server restart require a new check. The worker entry point can later be replaced without changing adapters.

## Configuration and tests

Configure defaults for `SPIDER_USER_AGENT`, `SPIDER_TIMEOUT`, `SPIDER_MAX_RETRIES`, and `SPIDER_REQUEST_DELAY` in `.env`, or change them in Admin **System Settings**. `SPIDER_MAX_CONCURRENCY` is fixed to `1`; legacy saved values greater than one are normalized to one on startup. Optional `GITHUB_TOKEN` and `ALLOW_PRIVATE_SOURCE_URLS` remain in `.env`; the token is never returned by the Settings API.

From `backend`, run `..\.venv\Scripts\python.exe -m pytest tests -q`. All adapter tests use HTTP mocks and do not use the internet. Run the Alembic migration before starting the updated backend: `..\.venv\Scripts\python.exe -m alembic upgrade head`.

If the database has no sources, add one in the Admin or deliberately run `scripts\seed_spider_demo.py --software-id <existing ID> --url <source URL> --adapter GITHUB_RELEASE` from the project root. The script does not run automatically and creates no software record.

For a read-only network probe without database writes, run `.venv\Scripts\python.exe scripts\probe_spider.py https://github.com/cli/cli --adapter GITHUB_RELEASE`.
