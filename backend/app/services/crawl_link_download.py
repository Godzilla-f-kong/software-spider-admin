"""Download direct files discovered in crawl results to the local backup archive."""
import re
import time
import base64
import binascii
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.core.enums import JobStatus
from app.downloader.base import DownloadProgress, DownloadRequest
from app.downloader.errors import DownloadError
from app.downloader.http_downloader import HttpDownloader
from app.downloader.policy import safe_component, safe_filename
from app.downloader.staging import StagingManager
from app.models import Job
from app.spider.classifier import ArtifactClassifier
from app.spider.errors import SpiderError
from app.spider.http import SpiderHttpClient, content_disposition_filename
from app.spider.normalizers import URLNormalizer, URLSafetyValidator
from app.storage.archive import ArchiveManager
from app.storage.providers.self_hosted_provider import SelfHostedPanProvider


def _unwrap_download_wrapper(url: str, http: SpiderHttpClient) -> str:
    """Unwrap common base64 redirectors while validating the decoded destination."""
    parts = urlsplit(url)
    if Path(parts.path).name.lower() not in {"go.php", "redirect.php", "out.php"}:
        return url
    query = parse_qs(parts.query)
    raw = next((query[key][0] for key in ("url", "u", "target", "link") if query.get(key)), None)
    if not raw:
        return url
    candidates: list[str] = []
    try:
        padded = raw + "=" * (-len(raw) % 4)
        candidates.append(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8").strip())
    except (ValueError, UnicodeError, binascii.Error):
        pass
    candidates.append(raw)
    validator = getattr(http, "validator", None) or URLSafetyValidator()
    for candidate in candidates:
        try:
            return validator.validate(candidate)
        except SpiderError:
            continue
    return url


def _is_download_wrapper(url: str) -> bool:
    return Path(urlsplit(url).path).name.lower() in {"go.php", "redirect.php", "out.php"}


def _resolve_links(url: str, job: Job) -> list[tuple[str, str]]:
    """Resolve direct-file wrappers and inspect a public share/download flow."""
    http = SpiderHttpClient()
    try:
        url = _unwrap_download_wrapper(url, http)
        classifier = ArtifactClassifier()
        head_says_html = False
        try:
            head, head_url = http.request("HEAD", url, max_bytes=0)
            head_type = head.headers.get("content-type", "").lower()
            head_says_html = "html" in head_type
            if "html" not in head_type and (head_url != url or
                    classifier.classify(urlsplit(head_url).path, head_url, "", head_type).package_type.value != "OTHER"):
                filename = safe_filename(content_disposition_filename(head.headers.get("content-disposition"))
                                         or urlsplit(head_url).path
                                         or job.payload.get("filename") or "download.bin")
                return [(head_url, filename)]
        except SpiderError:
            pass
        try:
            response, resolved = http.request("GET", url,
                                              headers={} if head_says_html else {"Range": "bytes=0-0"},
                                              max_bytes=2_000_000)
            if response.status_code == 206 and "html" in response.headers.get("content-type", "").lower():
                response, resolved = http.request("GET", url, max_bytes=2_000_000)
        except SpiderError as exc:
            raise DownloadError(exc.code, exc.message) from exc
        content_type = response.headers.get("content-type", "").lower()
        if "html" not in content_type and not response.text.lstrip().startswith(("<!", "<html")):
            return [(resolved, safe_filename(job.payload.get("filename") or urlsplit(resolved).path) or "download.bin")]

        soup = BeautifulSoup(response.text, "html.parser")
        access_code = job.payload.get("access_code")
        if access_code and re.fullmatch(r"[A-Za-z0-9]{3,12}", str(access_code)):
            # Only submit a visible, ordinary password form back to its own host.
            for form in soup.select("form")[:20]:
                password = form.select_one('input[type="password"], input[name*="pwd" i], input[name*="pass" i], input[name*="code" i]')
                if password is None:
                    continue
                action = str(form.get("action") or resolved)
                try:
                    action_url = URLNormalizer.normalize(action, resolved)
                    if urlsplit(action_url).hostname != urlsplit(resolved).hostname:
                        continue
                    fields = {str(field.get("name")): str(field.get("value") or "")
                              for field in form.select("input[name]")[:50]}
                    fields[str(password.get("name") or "pwd")] = str(access_code)
                    response, resolved = http.request("POST", action_url, data=fields,
                                                      allowed_host=(urlsplit(resolved).hostname or "").lower().removeprefix("www."),
                                                      max_bytes=2_000_000)
                    soup = BeautifulSoup(response.text, "html.parser")
                    break
                except SpiderError:
                    continue
        files: dict[str, str] = {}
        for anchor in soup.select("a[href]")[:800]:
            label = anchor.get_text(" ", strip=True)[:255]
            try:
                target = URLNormalizer.normalize(str(anchor.get("href")), resolved)
            except SpiderError:
                continue
            name = safe_filename(urlsplit(target).path) or safe_filename(label)
            classification = classifier.classify(name, target, label)
            if classification.package_type.value != "OTHER":
                files.setdefault(target, name)

        # Some hosts expose the file only after opening a labelled ordinary-download detail page.
        for anchor in soup.select('a[href]')[:800]:
            label = anchor.get_text(" ", strip=True)
            if not re.search(r"download|下载|高速|立即", label, re.I):
                continue
            try:
                target = URLNormalizer.normalize(str(anchor.get("href")), resolved)
            except SpiderError:
                continue
            if target in files:
                continue
            try:
                head, final_url = http.request("HEAD", target, max_bytes=0)
                content_type = head.headers.get("content-type", "")
                filename = safe_filename(content_disposition_filename(head.headers.get("content-disposition"))
                                         or urlsplit(final_url).path)
                classification = classifier.classify(filename, final_url, label, content_type)
                if "html" not in content_type.lower() and classification.package_type.value != "OTHER":
                    files.setdefault(final_url, filename)
                    continue
                detail, detail_url = http.request("GET", target, max_bytes=2_000_000)
            except SpiderError:
                try:
                    detail, detail_url = http.request("GET", target, max_bytes=2_000_000)
                except SpiderError:
                    continue
            if "html" not in detail.headers.get("content-type", "").lower():
                detail_name = safe_filename(urlsplit(detail_url).path)
                if classifier.classify(detail_name, detail_url, label,
                                       detail.headers.get("content-type", "")).package_type.value != "OTHER":
                    files.setdefault(detail_url, detail_name or "download.bin")
                continue
            detail_soup = BeautifulSoup(detail.text, "html.parser")
            for child in detail_soup.select("a[href]")[:400]:
                child_label = child.get_text(" ", strip=True)[:255]
                try:
                    child_url = URLNormalizer.normalize(str(child.get("href")), detail_url)
                except SpiderError:
                    continue
                child_name = safe_filename(urlsplit(child_url).path) or safe_filename(child_label)
                if classifier.classify(child_name, child_url, child_label).package_type.value != "OTHER":
                    files.setdefault(child_url, child_name)
                    continue
                if not re.search(r"download|下载|普通下载|立即", child_label, re.I):
                    continue
                try:
                    child_head, child_final = http.request("HEAD", child_url, max_bytes=0)
                except SpiderError:
                    continue
                disposition_name = safe_filename(
                    content_disposition_filename(child_head.headers.get("content-disposition")) or "")
                child_type = child_head.headers.get("content-type", "")
                if "html" not in child_type.lower() and classifier.classify(
                        disposition_name or child_name, child_final, child_label, child_type
                ).package_type.value != "OTHER":
                    files.setdefault(child_final, disposition_name or child_name or "download.bin")
        if not files:
            page_text = soup.get_text(" ", strip=True).lower()
            if re.search(r"captcha|验证码|请登录|登录后|login required|sign in to download|account required", page_text):
                raise DownloadError("MANUAL_REQUIRED", "The provider requires an authorized login or CAPTCHA")
            if re.search(r"付费|购买会员|开通会员|payment required|upgrade to premium", page_text):
                raise DownloadError("PAYMENT_REQUIRED", "The provider requires payment or a paid membership")
            raise DownloadError("SHARE_UNRESOLVED", "No public direct file link was found on the share page")
        return list(files.items())
    finally:
        http.close()


class CrawlLinkDownloadService:
    def download(self, db: Session, job: Job) -> None:
        payload = job.payload or {}
        source_url = payload.get("url")
        if not isinstance(source_url, str) or not source_url:
            raise DownloadError("INVALID_SOURCE", "Crawl result did not contain a valid URL")

        # Keep known direct URLs on the streaming path; inspect known redirect wrappers
        # because their .php endpoint commonly returns an HTML interstitial.
        if payload.get("kind") == "DIRECT_FILE" and not _is_download_wrapper(source_url):
            filename = safe_filename(payload.get("filename") or urlsplit(source_url).path) or "download.bin"
            targets = [(source_url, filename)]
        else:
            targets = _resolve_links(source_url, job)

        manager = ArchiveManager()
        staging = StagingManager()
        successful: list[dict] = []
        errors: list[dict] = []
        started = time.monotonic()

        def cancelled() -> bool:
            db.rollback()
            db.refresh(job)
            return job.status is JobStatus.CANCELLED

        for index, (target_url, filename) in enumerate(targets, start=1):
            try:
                if cancelled():
                    raise DownloadError("CANCELLED", "Download cancelled")
                part = staging.part(job.id)
                part.parent.mkdir(parents=True, exist_ok=True)

                def progress(value: DownloadProgress) -> None:
                    job.progress = min(99, int(((index - 1) + (value.downloaded / value.total if value.total else 0))
                                               * 100 / len(targets)))
                    job.message = f"Downloading file {index}/{len(targets)}: {value.downloaded} bytes"
                    job.result = {"files": successful, "errors": errors,
                                  "bytes_downloaded": value.downloaded, "total_bytes": value.total,
                                  "speed_bytes_per_second": round(value.speed)}
                    db.commit()

                downloaded = HttpDownloader().download(
                    DownloadRequest(job.id, target_url, filename, part), progress, cancelled)
                with part.open("rb") as stream:
                    signature = stream.read(512).lstrip().lower()
                if ((downloaded.content_type and "text/html" in downloaded.content_type.lower())
                        or signature.startswith((b"<!doctype html", b"<html", b"<form"))):
                    part.unlink(missing_ok=True)
                    raise DownloadError("SHARE_UNRESOLVED", "Resolved URL returned an HTML page, not a file")

                relative = Path("archive", "_crawl-backups",
                                safe_component(payload.get("candidate_name", "candidate")),
                                f"crawl-{payload.get('crawl_job_id', job.target_id)}",
                                f"link-{job.id}-{index}", safe_filename(downloaded.filename))
                manager.archive(part, relative)
                archived = manager.resolve_relative(relative.as_posix())
                successful.append({"source_url": target_url, "resolved_url": downloaded.resolved_url,
                                   "filename": downloaded.filename, "local_path": relative.as_posix(),
                                   "file_size": downloaded.file_size, "sha256": manager._sha256(archived),
                                   "md5": SelfHostedPanProvider._md5(archived)})
                job.result = {"files": successful, "errors": errors,
                              "bytes_downloaded": downloaded.file_size, "total_bytes": downloaded.file_size,
                              "speed_bytes_per_second": round(downloaded.file_size / max(downloaded.elapsed_seconds, .001))}
                job.progress = min(99, int(index * 100 / len(targets)))
                db.commit()
            except DownloadError as exc:
                if exc.code == "CANCELLED":
                    raise
                errors.append({"url": target_url, "code": exc.code, "message": exc.message})
            except Exception as exc:
                errors.append({"url": target_url, "code": "UNKNOWN_ERROR", "message": str(exc)[:500]})

        if not successful:
            details = "; ".join(f"{item['code']}: {item['message']}" for item in errors[:5])
            raise DownloadError("ALL_LINKS_FAILED", details or "No downloadable files were saved")
        job.result = {"files": successful, "errors": errors, "elapsed_seconds": round(time.monotonic() - started, 2)}
        job.message = f"Saved {len(successful)} file(s); {len(errors)} failed"
