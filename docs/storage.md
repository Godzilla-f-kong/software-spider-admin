# Phase 4: Storage providers and Baidu Pan

`SoftwareArtifact` remains the verified file record. `ArtifactStorage` records each local or remote location. The Baidu provider never changes software, release, variant, artifact, or SQL rows directly. `StorageService` checks permissions, creates jobs and writes storage/account rows; `storage_runner` performs queued uploads.

## Setup on Windows

1. Register an application in the [Baidu Netdisk Open Platform](https://yun.baidu.com/union/) and register the exact redirect URI `http://127.0.0.1:8000/api/v1/storage/accounts/baidu/oauth/callback` (or set your own URI in `.env`).
2. Set `BAIDU_APP_KEY`, `BAIDU_APP_SECRET`, and `BAIDU_APP_FOLDER` in the project `.env`. The folder must be the app folder authorized for the registered application; uploads go under `/apps/<folder>/`. Set `BAIDU_APP_ID` if the application has purchased and been granted the new file share service.
3. Keep `BAIDU_TOKEN_ENCRYPTION_KEY` in `.env` and in a secure backup. It is a Fernet key generated locally. Losing it means existing stored OAuth tokens cannot be decrypted; replacing it requires reconnecting the account.

   Generate a key in the project virtual environment when installing elsewhere: `.\.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Copy the output into `BAIDU_TOKEN_ENCRYPTION_KEY` in `.env` and keep it private.
4. Restart the backend. In **Settings**, click **Connect Baidu Pan**, approve OAuth in the new window, then refresh Settings. The account page shows status and expiry, never tokens.

The account uses OAuth authorization code and refresh token. No Baidu username/password or browser cookie is stored. Tokens are encrypted before saving in MySQL. The app key and secret remain in `.env`. Refresh happens before expiry and rotates stored tokens.

## Upload and share lifecycle

The artifact must be `VERIFIED`, have an existing safe local archive file, and have `redistribution_status=ALLOWED` set after an explicit admin confirmation. `UNKNOWN` and `PROHIBITED` block upload. This permission is also checked when the worker starts and again when a share is created.

From Artifact Detail → **Storage**, click **Upload to Baidu Pan**. This creates one `UPLOAD_STORAGE` job and one pending `ArtifactStorage` row. The bounded worker reads the archive in slices (default 4 MiB), calls Baidu's `precreate → locateupload → superfile2 upload → create` API, and records `fs_id`, remote path, progress and final status. It never reads the whole file into memory. A failed row can be retried; a successful row cannot be uploaded again accidentally. Interrupted running jobs become failed on backend startup, and pending jobs are resumed.

After upload success, **Create share** requests a 7-day Baidu share and stores its link, code and share ID. The [current official create-share endpoint](https://pan.baidu.com/union/doc/基础网盘服务/文件分享服务新/创建分享链接/) is a paid enterprise capability. The documented Open API does not expose cancel-share, so the Admin does not claim to disable remote shares. Cancel them in Baidu Pan; the `disable-share` API returns `501 NOT_SUPPORTED_BY_OPEN_API` until an official endpoint is available. Sharing is never performed automatically during upload.

`LOCAL` storage is managed by the existing verification/archive flow. The local provider validates archive paths and can query/delete a file internally; there is no public arbitrary-path file API. `PAN123` and `S3` remain unconfigured interface options.

## API

- `GET /api/v1/storage/providers`
- `GET /api/v1/storage/accounts`
- `GET /api/v1/storage/accounts/baidu/oauth/start`
- `GET /api/v1/storage/accounts/baidu/oauth/callback`
- `POST /api/v1/artifacts/{id}/redistribution`
- `POST /api/v1/artifacts/{id}/upload`
- `GET /api/v1/artifacts/{id}/storage`
- `POST /api/v1/storage/{id}/share`
- `POST /api/v1/storage/{id}/disable-share`

## Verification and limits

Run `..\.venv\Scripts\python.exe -m pytest tests\test_storage_phase4.py -q` from `backend`. Tests use a mock Baidu HTTP transport and a temporary SQLite database. They do not upload to a real account. Live OAuth, upload and share behavior must be checked with a small verified file after app credentials are configured. The provider follows Baidu's [precreate](https://pan.baidu.com/union/doc/基础网盘服务/上传/预上传/), [upload host lookup](https://pan.baidu.com/union/doc/基础网盘服务/上传/获取上传域名/) and [slice upload](https://pan.baidu.com/union/doc/基础网盘服务/上传/分片上传/) docs.
