# software_spider Admin

Phase 4 storage provider integration is documented in [Storage providers and Baidu Pan](docs/storage.md). The Baidu OAuth app key/secret and matching redirect URI must be configured in `.env` before connecting an account. Baidu uploads require a locally archived `VERIFIED` artifact and an explicit `ALLOWED` redistribution decision. The LAN cloud-drive integration is documented in [Self-hosted storage](docs/self-hosted-storage.md); it uses a service API key and a selected `file_arch` category. Creating and disabling a Baidu share are separate actions in Artifact Detail → Storage.

Software resource management and publishing Admin. Phase 1 provides the catalog and management UI. Phase 2 adds source adapters and release discovery. Phase 3 implements direct HTTP download, verification and local archive. Phase 4 adds storage providers, Baidu OAuth, upload jobs and share management.

Targeted candidate search across independent website URL pools is documented in [Targeted search](docs/targeted-search.md). New candidates and enabled website URLs are queued automatically. The single Spider worker scans candidates in priority order and checks each candidate across enabled sites until it finds a confirmed match or exhausts the sites. Progress and findings appear in the candidate table and Job Center. The crawler uses site search, sitemaps, categories and prioritized links; it resumes internally when a per-request page budget is reached. External Google Programmable Search and AI page-role assistance are optional, disabled until their `.env` credentials and settings are supplied.

## Architecture

`admin-web` (Vue 3, TypeScript, Vite, Element Plus) calls `backend` (FastAPI, Pydantic, SQLAlchemy). The backend uses MySQL through PyMySQL. Alembic owns schema migrations. Business actions live in `backend/app/services`; the API layer does not download files. `data` is reserved for staging, archive and failed files. `skills` contains placeholders for later content generators.

### Database relationships

```text
SoftwareCandidate --accept--> Software 1--N SoftwareRelease 1--N SoftwareVariant 1--N SoftwareArtifact 1--N ArtifactStorage
                           |                     |
                           +--N SoftwareSource  +--N GeneratedContent (optional release)
                           +--N CommerceListing (optional release/content)
Job(target_type, target_id) refers to a work target without cascading deletion.
```

`Software.slug` and `(software_id, version)` are unique. Duplicate variants and exact duplicate artifacts are checked in the service layer to allow multiple package formats and file sources. Foreign keys restrict deletion; software is archived through a dedicated action. MySQL `DATETIME` values use Beijing wall-clock time (Asia/Shanghai, UTC+8); the API returns timestamps with an explicit `+08:00` offset. Status transitions are validated per entity.

The database tables and columns have MySQL comments. Alembic applies schema and time migrations through `alembic upgrade head`. Run `.\.venv\Scripts\python.exe scripts\check_db_comments.py` from the project root to verify the connection target and comments without printing credentials. In a database client, refresh the table metadata after migration; table comments and column comments often appear in separate views.

Local artifact storage defaults to `.env` value `DATA_ROOT=F:/software_spider_bak`. The Settings page can override this path and other non-secret runtime settings; the directory must be writable by the account running the backend.

## Requirements

- Windows 10/11
- A standalone Python 3.10+ installation, not Conda
- Node.js 20+ recommended. This workspace has Node 14 globally, so `admin-web` installs a project-local Node 20 development dependency.
- MySQL 8 with existing `software_spider` database and a user authorized to create tables

## Backend setup

From the project root in PowerShell:

```powershell
E:\python10\python.exe -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
Copy-Item .env.example .env
```

If `.venv` already exists, keep it and use its executables. If `.env` already exists, keep it. Edit `.env` with `DB_USER` and `DB_PASSWORD`. The default host, port and database name are listed in `.env.example`. `.env` is ignored by Git. Never commit its contents.

Run migration from `backend`:

```powershell
cd backend
..\.venv\Scripts\alembic.exe upgrade head
```

Start backend from the project root with `scripts\start_backend.bat`, or:

```powershell
cd backend
..\.venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8000 --reload
```

API documentation: http://127.0.0.1:8000/docs  
Health: http://127.0.0.1:8000/api/v1/health

## Frontend setup

```powershell
cd admin-web
npm install --cache .npm-cache
npm run build
npm run dev
```

Or start with `scripts\start_frontend.bat` after installing dependencies. Open http://127.0.0.1:5173. Vite proxies `/api` to the backend on port 8000. The project-local Node dependency lets `npm run` use Node 20 even when the global Node is 14.

Use the language selector in the upper right to switch between Simplified Chinese and English. The selection is saved in the browser.

## API and UI

All API endpoints use `/api/v1`. Resources: `candidates`, `software`, `sources`, `releases`, `variants`, `artifacts`, `links`, `storage`, `content`, `listings`, `jobs`. Each has paginated `GET /`, `POST /`, `GET /{id}` and (except jobs) `PATCH /{id}`. List endpoints accept `page`, `page_size`, `search`, resource-specific filters and whitelisted `sort`. Errors use `{ "error": { "code": 422, "message": "..." } }`.

Special actions: candidate accept, software archive, artifact download and verify. Nested read routes exist for software releases and sources. Dashboard and Settings have separate read endpoints. The UI includes Dashboard, Candidates, Software, Releases, Variants, Artifacts, Sources, Downloads, Storage, Content, Publishing, Jobs and Settings. Software detail groups its related records into tabs. Artifact detail shows its chain and storage locations.

Resource lists show their record IDs. Candidate rows show both the candidate ID and the accepted software ID; accepting a candidate opens the new software record. Related records are selected by searchable names and release/file context in forms and filters. The `/api/v1/lookups/{kind}` endpoint supplies up to 50 matching options per request rather than loading an entire table.

## Optional demo data

No demo records are inserted automatically. To insert one 7-Zip product and its release/variant/artifact:

```powershell
cd backend
..\.venv\Scripts\python.exe ..\scripts\seed_demo_data.py
```

## Common issues

- **Database disconnected:** Check MySQL is reachable, `.env` credentials, database existence and grants. The health endpoint reports degraded state if it cannot connect.
- **Migration fails:** Run it from `backend` using the local `.venv` Alembic executable. Verify the MySQL user has schema privileges.
- **Frontend cannot reach API:** Start the backend on port 8000, then the frontend on 5173.
- **Node syntax error:** Use Node 20+ or reinstall the project-local Node dependency with `npm install --cache .npm-cache`.
- **Pending download never completes:** Check that the backend download worker is running and inspect the Job error. Restarting the backend recovers pending download jobs.

## Current limits

No authentication or RBAC is provided. Bind the development servers to localhost. Cloud upload, AI generation, marketplace login/publishing and Personal Website integration remain out of scope.
# Phase 2 Spider / Release Discovery

### 两个独立的人工输入池：候选软件与网站主页

商品标题工作簿导入工具：`scripts/import_shop_titles.py` 针对 2026-10-06 的店铺商品列表逐条整理了可识别的软件英文名称。先在项目根目录使用本地虚拟环境安装依赖，然后运行预览；确认后加 `--apply` 导入。脚本按名称去重，仅设置候选名称及必需的规范化名称，分类和其他字段保持默认。没有明确软件名称的标题会跳过，原有候选记录不会被改动。

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
$env:PYTHONPATH = 'backend'
.\.venv\Scripts\python.exe scripts\import_shop_titles.py 'F:\商业\卖软件服务的商业分析\择邻素材\店铺分析_商品列表__2026-10-06.xlsx'
.\.venv\Scripts\python.exe scripts\import_shop_titles.py 'F:\商业\卖软件服务的商业分析\择邻素材\店铺分析_商品列表__2026-10-06.xlsx' --apply
```

候选软件和 URL 抓取池均由管理员人工录入。**候选软件无需填写 URL；URL 池只需填写网站主页，不需要预先指定软件 ID 或具体文章地址。** 新增候选或启用 URL 池后，后台会自动将未完成的候选与启用的网站配对并排队；同一时刻只执行一个 Spider Job。每个候选按优先级扫描多个站点，遇到符合目标条件的资源就结束该候选任务并处理下一个。URL 池与旧的 `SoftwareSource` 是不同概念：前者遍历站内链接并寻找候选；后者是确认匹配后、用于某个正式软件的版本和文件解析来源。

以 FusionTestTool 为例：

1. 在 **软件发现 → 软件候选池** 新增 `FusionTestTool`；“候选参考 URL”可以留空。
2. 在 **软件发现 → URL 抓取池** 新增网站主页 `https://www.tree666.com/`。测试时可设“单次最多访问页面”为 `6`、“站内最大遍历深度”为 `1`。
3. 新增候选和启用 URL 池后系统自动创建 `CRAWL` Job。进入 **后台任务** 可查看当前站点、访问进度、已检查站点和匹配结果。扫描从主页沿同站链接发现页面，按标题或 H1 匹配候选；找到符合条件的资源后停止扫描该候选，自动转向队列中的下一个候选。扫描结果保存在 Job 中，不会自动新增正式软件或下载文件。
4. 审核匹配页面后，在候选池点击 **接受**（若尚未接受），再回到扫描结果点击 **建立软件来源**。该操作仅为这个经确认的页面建立 `SoftwareSource`；重复点击会复用已有来源。
5. 在软件档案的 **已收录软件来源** 中点击 **发现版本**，预览后 **全部导入**，最后在 **安装包文件** 中点击 **下载**。

本机测试曾在 URL 池只填写 `https://www.tree666.com/` 时匹配到 `https://www.tree666.com/post/137.html` 和版本 `3.2`。现在新增候选或 URL 后会自动排队；扫描遵守 `robots.txt`，只读取公开 HTML，达到单轮请求预算后从断点继续。需要 JavaScript、登录或验证码的页面不会被绕过。仍可提高 URL 池的遍历深度以覆盖更深的文章。详情见 [Spider architecture](docs/spider.md)。

### Editable settings and Beijing time

Open **System Settings** in the Admin to edit the local archive directory and Spider enable switch, User-Agent, timeout, retries, and request delay. Spider Job concurrency is fixed at one to preserve the global serial queue. Save writes the non-secret overrides to the `system_settings` table; they are restored when the backend starts. The same operation is available through `PATCH /api/v1/settings`. Database credentials and API tokens remain in `.env` and are never returned by the Settings API.

Migration `b319a76e52d4` converted existing naive UTC timestamps to Beijing time by adding eight hours. New database timestamps use Beijing wall-clock time, and API timestamps include `+08:00`. The Admin formats them in `Asia/Shanghai` regardless of browser time zone. Date-only release dates remain dates. This changes application and database timestamps; it does not change the Windows system clock.

The Admin now supports source discovery previews, review and idempotent import into Software → Release → Variant → Artifact. Source adapters are isolated from persistence and never download installer files. See [Spider architecture](docs/spider.md) for adapter contracts, lifecycle, security policy, release checks, background jobs and tests.

After updating dependencies with `.venv\Scripts\python.exe -m pip install -r backend\requirements.txt`, run the existing Alembic migrations from `backend` using `..\.venv\Scripts\python.exe -m alembic upgrade head`. Add spider settings from `.env.example` to `.env` as needed. `GITHUB_TOKEN` is optional. In the Admin, add a source to a software record, choose an adapter, click **Discover**, review the Job-backed preview, then click **Import all**. The Job Center shows both discovery and release-check jobs. Unknown versions can be filled in the preview; those still unknown are skipped on import.

### Spider test commands (Windows PowerShell)

For HTML sources, preview shows cloud shares and download entries separately from installer files. Links can be imported without a known version; they remain attached to the Software and Source for review. Installer artifacts still require a reliable version.

Run these commands **from the project root** (`H:\allPro\software_spider\software_spider_admin`). All Python commands use the project `.venv`.

**Read-only probe, no MySQL writes:** the following real GitHub example uses the public Releases API. It prints release and artifact counts; it does not download installer files.

```powershell
.\.venv\Scripts\python.exe scripts\probe_spider.py https://github.com/cli/cli --adapter GITHUB_RELEASE
```

For a normal HTML download page or a direct installer URL, replace the sample variables with URLs you are permitted to access. The `ghxi.com` command is a live, read-only example; other example domains are placeholders. Cloud-share entries are reported as links with access codes when present, without creating installer artifacts.

```powershell
$htmlUrl = 'https://your-vendor.example/downloads'
.\.venv\Scripts\python.exe scripts\probe_spider.py $htmlUrl --adapter GENERIC_HTML

# Cloud share example: reports Quark/Xunlei/download links and page access codes
.\.venv\Scripts\python.exe scripts\probe_spider.py https://www.ghxi.com/ddu.html --adapter GENERIC_HTML

$fileUrl = 'https://your-vendor.example/files/app-1.2.3-win-x64.zip'
.\.venv\Scripts\python.exe scripts\probe_spider.py $fileUrl --adapter STATIC_URL

$jsonUrl = 'https://your-vendor.example/releases.json'
.\.venv\Scripts\python.exe scripts\probe_spider.py $jsonUrl --adapter JSON_API
```

`JSON_API` expects an object containing a `releases` array with `version` and `assets` entries, as described in [Spider architecture](docs/spider.md). `BROWSER` and `MANUAL` require manual handling and are not network probes. If an HTML or static source has no reliable version, the preview reports it and the Admin lets you enter one before import.

**Test an already known GitHub repository through the Admin:** open `http://127.0.0.1:5173`, create an active software record named `GitHub CLI` with a unique slug such as `github-cli-test`, then open its **Catalog Sources / 已收录软件来源** tab. Add a source with `source_type=GITHUB`, `source_url=https://github.com/cli/cli`, `adapter_type=GITHUB_RELEASE`, and `enabled=true`. Click **Discover / 发现版本** to see the Job-backed preview. **Import all / 全部导入** writes the discovered Release, Variant and Artifact records; reviewing the preview alone does not write those catalog records. This repository-specific workflow is separate from the independent website URL crawl pool above. This example repository has many releases, so review the detected count before importing all.

The same workflow can be tested with PowerShell API commands. **These commands create one Software, one Source and Job records in MySQL.** Change `$softwareName` and `$sourceUrl` to specify your own target; the generated slug avoids collisions. Start the backend first.

```powershell
$base = 'http://127.0.0.1:8000/api/v1'
$softwareName = 'GitHub CLI Spider Test'
$sourceUrl = 'https://github.com/cli/cli'
$slug = 'spider-test-' + (Get-Date -Format 'yyyyMMddHHmmss')

$softwareBody = @{ name = $softwareName; slug = $slug; status = 'ACTIVE' } | ConvertTo-Json
$software = Invoke-RestMethod -Method Post -Uri "$base/software" -ContentType 'application/json' -Body $softwareBody
$sourceBody = @{ software_id = $software.id; source_type = 'GITHUB'; source_url = $sourceUrl; adapter_type = 'GITHUB_RELEASE'; enabled = $true } | ConvertTo-Json
$source = Invoke-RestMethod -Method Post -Uri "$base/sources" -ContentType 'application/json' -Body $sourceBody

$previewJob = Invoke-RestMethod -Method Post -Uri "$base/sources/$($source.id)/discover/preview"
$previewJob = Invoke-RestMethod -Uri "$base/jobs/$($previewJob.id)"
$previewJob.status
```

Preview runs in the background. If status is `PENDING` or `RUNNING`, repeat the `GET /jobs/{id}` command after a few seconds. When status is `SUCCESS`, inspect the detected versions and file count before deciding whether to import:

```powershell
$previewJob = Invoke-RestMethod -Uri "$base/jobs/$($previewJob.id)"
$previewJob.result.discovery.releases | Select-Object version, status, @{Name='artifacts';Expression={$_.artifacts.Count}}
$previewJob.error_message
```

**Optional import:** this next command writes Release, Variant and Artifact records. Use it only after reviewing the preview. The returned import Job can be checked with the same `GET /jobs/{id}` pattern. A separate version check creates a `CHECK_RELEASE` Job without importing discoveries.

```powershell
$importBody = @{ preview_job_id = $previewJob.id } | ConvertTo-Json
$importJob = Invoke-RestMethod -Method Post -Uri "$base/sources/$($source.id)/discover/import" -ContentType 'application/json' -Body $importBody
$importJob = Invoke-RestMethod -Uri "$base/jobs/$($importJob.id)"

$checkJob = Invoke-RestMethod -Method Post -Uri "$base/software/$($software.id)/check-release"
$checkJob = Invoke-RestMethod -Uri "$base/jobs/$($checkJob.id)"
```

For a Generic HTML or Static URL source through this API, change `source_type`, `source_url`, and `adapter_type` in `$sourceBody` to match the source. Supported adapter values are `GITHUB_RELEASE`, `GENERIC_HTML`, `STATIC_URL`, and `JSON_API`; `BROWSER` and `MANUAL` require human review.

If the software record already exists and you know its ID, this optional command adds the source without starting discovery. Replace `1` with the ID shown in the Admin; it does not create a software record.

```powershell
$softwareId = 1
.\.venv\Scripts\python.exe scripts\seed_spider_demo.py --software-id $softwareId --url https://github.com/cli/cli --adapter GITHUB_RELEASE
```

**Check the running service and schema:** start the backend with `scripts\start_backend.bat` and the frontend with `scripts\start_frontend.bat` in separate PowerShell windows, then run:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
Invoke-RestMethod http://127.0.0.1:8000/api/v1/settings
.\.venv\Scripts\python.exe scripts\check_db_comments.py
```

API documentation is at `http://127.0.0.1:8000/docs`. Source preview, import, and version-check endpoints are listed there. A successful preview/import Job can be inspected in the Admin Job Center.

**Run offline tests and migration checks:** tests use mocked HTTP responses and never contact live source sites.

```powershell
Push-Location backend
..\.venv\Scripts\python.exe -m pytest tests -q
..\.venv\Scripts\python.exe -m alembic current
..\.venv\Scripts\python.exe -m alembic check
Pop-Location
```
# Phase 3: Direct downloader and local verification

See [Downloader architecture](docs/downloader.md). After a Spider import creates an Artifact with a direct HTTP/HTTPS `source_url`, open its detail page and click **Download**. The Admin creates a `DOWNLOAD` Job, streams to staging, then creates a `VERIFY` Job. Check the Job Center for byte progress, speed, and errors. A verified file moves into `DATA_ROOT/archive`; uncertain files wait in staging for manual approval, and rejected files move to `DATA_ROOT/failed`. The current local path is configured by `DATA_ROOT` (for this installation, `F:/software_spider_bak`). Cloud share links are discovery records and are not direct downloads.

New `.env` options include `DOWNLOAD_TIMEOUT`, `DOWNLOAD_CONNECT_TIMEOUT`, `DOWNLOAD_MAX_RETRIES`, `DOWNLOAD_CHUNK_SIZE`, `DOWNLOAD_MAX_CONCURRENCY`, `DOWNLOAD_MAX_FILE_SIZE`, `DOWNLOAD_MIN_FREE_SPACE`, `DOWNLOAD_USER_AGENT`, `DOWNLOAD_ALLOWED_DOMAINS`, and `DOWNLOAD_ALLOWED_REDIRECT_DOMAINS`. Copy defaults from `.env.example`, then restart the backend. Apply the new migration from `backend` with `..\.venv\Scripts\python.exe -m alembic upgrade head`. Run offline downloader tests with `..\.venv\Scripts\python.exe -m pytest tests\test_downloader.py -q`. Downloads use only public HTTP/HTTPS resources and do not grant redistribution rights.

To run the small real HTTP pipeline probe without changing MySQL or `DATA_ROOT`, run `.venv\Scripts\python.exe scripts\probe_download_pipeline.py` from the project root. It downloads the official 7-Zip `7zr.exe` release to a temporary project subdirectory, runs `DOWNLOAD` and `VERIFY` Jobs against an isolated SQLite database, checks the archived file and removes the temporary data.
