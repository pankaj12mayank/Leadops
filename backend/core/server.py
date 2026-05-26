import asyncio
import hashlib
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from backend.auth.jwt_auth import create_access_token, decode_access_token, hash_password, verify_password
from backend.config.loader import BASE_DIR, CONFIG_PATH, load_config, setup_logging
from backend.core.browser import check_health, close_browser, init_browser
from backend.core.exporter import EXPORTS_DIR, cleanup_expired_exports, export_still_valid, get_export_path
from backend.core.job_manager import JobManager
from backend.core.security import (
    check_rate_limit,
    hash_ip,
    prune_rate_limits,
    validate_max_pages,
    validate_query,
    validate_source,
)
from backend.payments.stripe_checkout import (
    configure_stripe,
    create_checkout_session,
    get_payment_status,
    handle_webhook_event,
)
from backend.scrapers.base import NavigationError, ScraperError
from backend.storage.database import (
    count_leads,
    get_admin_user,
    create_admin_user,
    update_admin_password,
    get_job,
    get_leads_by_job,
    get_preview_access,
    grant_preview_access,
    init_db,
    list_jobs,
    list_leads,
)

app = FastAPI(title="Lead Extraction API", version="1.0.0")

_api_logger = setup_logging("api")
init_db()
job_manager = JobManager(_api_logger)


def _error_response(status: int, code: str, message: str):
    return JSONResponse(
        status_code=status,
        content={"success": False, "error": {"code": code, "message": message}},
    )


def _success_response(data: Any) -> dict[str, Any]:
    return {"success": True, "data": data}


@app.exception_handler(ScraperError)
async def _scraper_error_handler(request: Request, exc: ScraperError):
    status = 503
    if isinstance(exc, NavigationError):
        status = 502
    return _error_response(status, type(exc).__name__, str(exc))


@app.exception_handler(Exception)
async def _generic_exception_handler(request: Request, exc: Exception):
    ip = request.client.host if request.client else "unknown"
    _api_logger.exception("Unhandled exception on %s %s from %s: %s", request.method, request.url.path, ip, exc)
    return _error_response(500, "INTERNAL_ERROR", "An unexpected error occurred")


@app.middleware("http")
async def _rewrite_api_prefix(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api"):
        remaining = path[4:] or "/"
        request.scope["path"] = remaining
        raw_path = request.scope.get("raw_path", b"")
        if raw_path:
            request.scope["raw_path"] = raw_path[len(b"/api"):] or b"/"
    return await call_next(request)


@app.middleware("http")
async def _timeout_middleware(request: Request, call_next):
    try:
        return await asyncio.wait_for(call_next(request), timeout=120.0)
    except TimeoutError:
        return _error_response(408, "TIMEOUT", "Request timed out")


@app.middleware("http")
async def _request_logging_middleware(request: Request, call_next):
    path = request.url.path
    method = request.method
    ip = request.client.host if request.client else "unknown"
    start = time.time()
    response = await call_next(request)
    elapsed = time.time() - start
    if elapsed > 1.0:
        _api_logger.info("%s %s from %s took %.2fs → %d", method, path, ip, elapsed, response.status_code)
    return response


_startup_cfg = load_config()
_cors_origins = _startup_cfg.get("api", {}).get("allowed_origins", ["http://localhost:5173"])
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_stripe_secret = os.environ.get("STRIPE_SECRET_KEY", "")
_stripe_webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
if _stripe_secret:
    configure_stripe(_stripe_secret)
    _api_logger.info("Stripe configured (key prefix: %s)", _stripe_secret[:8])
else:
    _api_logger.warning("STRIPE_SECRET_KEY not set — payments disabled")

_admin_email = os.environ.get("ADMIN_EMAIL", "admin@leadops.local")
_admin_password = os.environ.get("ADMIN_PASSWORD", "")
if _admin_password:
    existing = get_admin_user(_admin_email)
    if not existing:
        create_admin_user(_admin_email, hash_password(_admin_password))
        _api_logger.info("Admin user created: %s", _admin_email)
    _api_logger.info("Admin auth configured for: %s", _admin_email)
else:
    _api_logger.warning("ADMIN_PASSWORD not set — admin endpoints disabled")


async def require_admin(request: Request):
    if not _admin_password:
        raise HTTPException(status_code=503, detail="Admin auth not configured")
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")
    token = auth[7:]
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return payload


@app.on_event("startup")
async def _on_startup() -> None:
    _api_logger.info("API server starting up")
    prune_rate_limits()
    cleanup_expired_exports(_api_logger)
    cfg = load_config()
    browser_ok = await init_browser(cfg)
    if browser_ok:
        _api_logger.info("Browser initialized for API")
    else:
        _api_logger.warning("Browser initialization failed — jobs will fail until browser is available")
    await job_manager.start()
    _api_logger.info("Job manager started")


@app.on_event("shutdown")
async def _on_shutdown() -> None:
    _api_logger.info("API server shutting down")
    await job_manager.stop()
    await close_browser()
    logging.shutdown()


class StartQuery(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    max_pages: int = Field(default=5, ge=1, le=20)


class StartMapsQuery(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    max_cycles: int = Field(default=30, ge=1, le=100)


class StartLinkedinQuery(BaseModel):
    csv_path: str = Field(default="", max_length=500)


class ExportFile(BaseModel):
    path: str
    filename: str
    size_bytes: int
    source: str
    last_modified: str
    type: str = "raw"


EXPORT_SOURCES = ["agency", "startup", "local", "merged"]


def _export_type(source: str, filename: str) -> str:
    return "merged" if source == "merged" else "raw"


def _scan_export_files() -> list[ExportFile]:
    files: list[ExportFile] = []
    export_dir = BASE_DIR / "content"
    if not export_dir.exists():
        return files

    for subdir in export_dir.iterdir():
        if not subdir.is_dir():
            continue
        source_name = subdir.name
        for fpath in sorted(subdir.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                stat = fpath.stat()
                files.append(
                    ExportFile(
                        path=str(fpath.relative_to(BASE_DIR)),
                        filename=fpath.name,
                        size_bytes=stat.st_size,
                        source=source_name,
                        last_modified=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                        type=_export_type(source_name, fpath.name),
                    )
                )
            except (OSError, PermissionError):
                continue
    return files


@app.post("/start/clutch")
async def start_clutch(body: StartQuery, request: Request):
    validate_source("clutch")
    q = validate_query(body.query)
    _ = validate_max_pages(body.max_pages)
    client_ip = request.client.host if request.client else "unknown"
    check_rate_limit(hash_ip(client_ip), "scrape")
    query_str = f"{q}|{body.max_pages}"
    job_id = await job_manager.enqueue("clutch", query_str)
    _api_logger.info("Clutch scraper queued: query='%s', max_pages=%d, job_id=%d", q, body.max_pages, job_id)
    return _success_response({"job_id": job_id, "source": "clutch", "status": "queued"})


@app.post("/start/goodfirms")
async def start_goodfirms(body: StartQuery, request: Request):
    validate_source("goodfirms")
    q = validate_query(body.query)
    _ = validate_max_pages(body.max_pages)
    client_ip = request.client.host if request.client else "unknown"
    check_rate_limit(hash_ip(client_ip), "scrape")
    query_str = f"{q}|{body.max_pages}"
    job_id = await job_manager.enqueue("goodfirms", query_str)
    _api_logger.info("GoodFirms scraper queued: query='%s', max_pages=%d, job_id=%d", q, body.max_pages, job_id)
    return _success_response({"job_id": job_id, "source": "goodfirms", "status": "queued"})


@app.post("/start/maps")
async def start_maps(body: StartMapsQuery, request: Request):
    validate_source("maps")
    q = validate_query(body.query)
    client_ip = request.client.host if request.client else "unknown"
    check_rate_limit(hash_ip(client_ip), "scrape")
    job_id = await job_manager.enqueue("maps", q)
    _api_logger.info("Maps scraper queued: query='%s', max_cycles=%d, job_id=%d", q, body.max_cycles, job_id)
    return _success_response({"job_id": job_id, "source": "maps", "status": "queued"})


@app.post("/start/linkedin")
async def start_linkedin(body: StartLinkedinQuery, request: Request):
    validate_source("linkedin")
    client_ip = request.client.host if request.client else "unknown"
    check_rate_limit(hash_ip(client_ip), "scrape")
    csv_path = body.csv_path.strip() if body.csv_path else ""
    if not csv_path:
        csv_path = str(BASE_DIR / "content" / "startup" / "input_companies.csv")
    job_id = await job_manager.enqueue("linkedin", csv_path)
    _api_logger.info("LinkedIn enrichment queued: csv='%s', job_id=%d", csv_path, job_id)
    return _success_response({"job_id": job_id, "source": "linkedin", "status": "queued"})


@app.post("/stop/{source}")
async def stop_scraper(source: str):
    current_id = job_manager.current_job_id()
    if current_id is None:
        raise HTTPException(status_code=404, detail="No job currently running")
    job = job_manager.get_job(current_id)
    if job is None or job["source"] != source:
        raise HTTPException(status_code=404, detail=f"No running job for source '{source}'")
    await job_manager.cancel_job(current_id)
    _api_logger.info("Job %d (%s) cancellation requested", current_id, source)
    return _success_response({"source": source, "status": "cancelling"})


@app.post("/merge")
async def start_merge():
    from backend.storage.merge import run_merge_engine

    async def wrapper():
        return await run_merge_engine(_api_logger, confirm=True)

    task = asyncio.create_task(wrapper())
    _api_logger.info("Merge started")
    return _success_response({"source": "merge", "status": "started"})


@app.post("/cleanup")
async def trigger_cleanup():
    from backend.storage.merge import cleanup_old_exports as cleanup_merge

    cfg = load_config()
    retention = cfg.get("export", {}).get("retention_days", 30)
    max_size = cfg.get("export", {}).get("max_size_mb", 500)
    merge_deleted = cleanup_merge(_api_logger, retention_days=retention, max_size_mb=max_size)
    export_deleted = cleanup_expired_exports(_api_logger)
    _api_logger.info("Cleanup removed %d merge file(s) and %d export(s)", merge_deleted, export_deleted)
    return _success_response({"deleted_files": merge_deleted + export_deleted, "retention_days": retention})


@app.get("/status")
async def get_status():
    jobs = job_manager.list_jobs(limit=20)
    current_id = job_manager.current_job_id()
    current_job = job_manager.get_job(current_id) if current_id else None
    return _success_response({
        "current_job": current_job,
        "total_jobs": len(jobs),
        "jobs": jobs,
    })


@app.get("/exports")
async def get_exports():
    files: list[dict[str, Any]] = []
    if EXPORTS_DIR.exists():
        for fpath in sorted(EXPORTS_DIR.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                stat = fpath.stat()
                job_id = int(fpath.stem)
                files.append({
                    "job_id": job_id,
                    "filename": fpath.name,
                    "size_bytes": stat.st_size,
                    "last_modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                    "valid": export_still_valid(job_id),
                })
            except (OSError, ValueError):
                continue

    total_size = sum(f["size_bytes"] for f in files)
    return _success_response({
        "total_files": len(files),
        "total_size_bytes": total_size,
        "total_size_kb": round(total_size / 1024, 1),
        "files": files,
    })


def _validate_file_path(file_path: str) -> Path:
    full_path = (BASE_DIR / file_path).resolve()
    try:
        full_path.relative_to(BASE_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Path traversal denied")
    if not full_path.exists() or not full_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return full_path


@app.get("/download/{file_path:path}")
async def download_export(file_path: str):
    full_path = _validate_file_path(file_path)
    media_type = "text/csv" if full_path.suffix == ".csv" else "application/octet-stream"
    safe_name = "".join(c for c in full_path.name if c.isascii() and c not in "\r\n\"\\")
    return FileResponse(
        path=str(full_path),
        media_type=media_type,
        filename=safe_name,
    )


@app.get("/download/job/{job_id}")
async def download_job_export(job_id: int):
    p = get_export_path(job_id)
    if not p.exists():
        raise HTTPException(status_code=404, detail="Export not found")
    if not export_still_valid(job_id):
        raise HTTPException(status_code=410, detail="Export has expired (7-day TTL)")
    job = get_job(job_id)
    if not job or job.get("payment_status", "unpaid") != "paid":
        raise HTTPException(status_code=402, detail="Payment required — CSV download is locked")
    media_type = "text/csv"
    safe_name = "".join(c for c in p.name if c.isascii() and c not in "\r\n\"\\")
    return FileResponse(
        path=str(p),
        media_type=media_type,
        filename=safe_name,
    )


@app.delete("/export/{file_path:path}")
async def delete_export(file_path: str, _admin=Depends(require_admin)):
    full_path = _validate_file_path(file_path)
    try:
        full_path.unlink()
        _api_logger.info("Deleted export file: %s", file_path)
        return _success_response({"deleted": True, "path": file_path})
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete file: {e}")


@app.get("/db/jobs")
async def db_jobs(source: str | None = Query(None), status: str | None = Query(None), limit: int = Query(50)):
    return _success_response({"jobs": list_jobs(source=source, status=status, limit=limit)})


@app.get("/db/jobs/{job_id}")
async def db_job_detail(job_id: int):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job["leads_count"] = count_leads(source=job["source"])
    return _success_response({"job": job})


@app.get("/db/jobs/{job_id}/leads")
async def db_job_leads(job_id: int):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    leads = get_leads_by_job(job_id)
    return _success_response({"leads": leads, "total": len(leads)})


@app.get("/db/leads")
async def db_leads(source: str | None = Query(None), limit: int = Query(100), offset: int = Query(0)):
    return _success_response({
        "leads": list_leads(source=source, limit=limit, offset=offset),
        "total": count_leads(source=source),
    })


def _hash_ip(client_ip: str) -> str:
    return hashlib.sha256(client_ip.encode()).hexdigest()


@app.get("/preview/status/{job_id}")
async def preview_status(job_id: int, request: Request):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    client_ip = request.client.host if request.client else "unknown"
    ip_hash = _hash_ip(client_ip)
    record = get_preview_access(job_id, ip_hash)
    return _success_response({
        "previewed": record is not None,
        "viewed_at": record["viewed_at"] if record else None,
    })


@app.post("/preview/job/{job_id}")
async def unlock_preview(job_id: int, request: Request):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] != "completed":
        raise HTTPException(status_code=400, detail="Job is not completed yet")
    client_ip = request.client.host if request.client else "unknown"
    ip_hash = _hash_ip(client_ip)
    record = get_preview_access(job_id, ip_hash)
    if record:
        return _success_response({"granted": False, "reason": "already_previewed"})
    ok = grant_preview_access(job_id, ip_hash)
    if not ok:
        return _success_response({"granted": False, "reason": "conflict"})
    _api_logger.info("Preview unlocked job %d for ip_hash=%s", job_id, ip_hash[:12])
    return _success_response({"granted": True})


SITE_CONTENT_PATH = BASE_DIR / "content" / "site-content.json"


@app.get("/content")
async def get_site_content():
    if not SITE_CONTENT_PATH.exists():
        raise HTTPException(status_code=404, detail="Site content not found")
    try:
        import json
        raw = SITE_CONTENT_PATH.read_text(encoding="utf-8")
        return JSONResponse(content=json.loads(raw))
    except (json.JSONDecodeError, OSError) as e:
        raise HTTPException(status_code=500, detail=f"Failed to read site content: {e}")


@app.get("/health")
async def health():
    browser_ok = await check_health()
    return _success_response({
        "status": "ok",
        "version": "1.0.0",
        "browser_session": "active" if browser_ok else "inactive",
        "current_job_id": job_manager.current_job_id(),
        "python_version": sys.version.split()[0],
    })


class CheckoutRequest(BaseModel):
    job_id: int
    success_url: str = ""
    cancel_url: str = ""


@app.post("/stripe/checkout")
async def stripe_checkout(body: CheckoutRequest, request: Request):
    if not _stripe_secret:
        raise HTTPException(status_code=503, detail="Payments not configured (STRIPE_SECRET_KEY missing)")
    job = get_job(body.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] != "completed":
        raise HTTPException(status_code=400, detail="Job is not completed yet")

    base_url = str(request.base_url).rstrip("/")
    success_url = body.success_url or f"{base_url}/results"
    cancel_url = body.cancel_url or f"{base_url}/results"
    checkout_url = create_checkout_session(body.job_id, success_url, cancel_url)
    if not checkout_url:
        raise HTTPException(status_code=500, detail="Failed to create checkout session")
    _api_logger.info("Stripe checkout URL generated for job %d", body.job_id)
    return _success_response({"checkout_url": checkout_url})


@app.post("/stripe/webhook")
async def stripe_webhook(request: Request):
    if not _stripe_webhook_secret:
        raise HTTPException(status_code=503, detail="Stripe webhook secret not configured")
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    if not sig_header:
        raise HTTPException(status_code=400, detail="Missing stripe-signature header")
    result = handle_webhook_event(payload, sig_header, _stripe_webhook_secret)
    if result is None:
        raise HTTPException(status_code=400, detail="Webhook verification failed")
    return _success_response({"received": True, "event_id": result})


@app.get("/stripe/check/{job_id}")
async def stripe_check_payment(job_id: int):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    status = get_payment_status(job_id)
    return _success_response(status)


# ── Admin Auth ──────────────────────────────────────────


class AdminLoginRequest(BaseModel):
    email: str
    password: str


class AdminChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


@app.post("/admin/login")
async def admin_login(body: AdminLoginRequest):
    if not _admin_password:
        raise HTTPException(status_code=503, detail="Admin auth not configured")
    if body.email != _admin_email:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    admin = get_admin_user(body.email)
    if not admin or not verify_password(body.password, admin["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token({"sub": body.email, "admin": True})
    _api_logger.info("Admin login: %s", body.email)
    return _success_response({"token": token, "email": body.email})


@app.post("/admin/change-password")
async def admin_change_password(body: AdminChangePasswordRequest, _admin=Depends(require_admin)):
    admin = get_admin_user(_admin_email)
    if not admin or not verify_password(body.old_password, admin["password_hash"]):
        raise HTTPException(status_code=401, detail="Old password is incorrect")
    new_hash = hash_password(body.new_password)
    update_admin_password(_admin_email, new_hash)
    _api_logger.info("Admin password changed")
    return _success_response({"changed": True})


@app.get("/admin/jobs")
async def admin_list_jobs(_admin=Depends(require_admin)):
    jobs = list_jobs(limit=100)
    return _success_response({"jobs": jobs, "total": len(jobs)})


@app.post("/admin/jobs/{job_id}/retry")
async def admin_retry_job(job_id: int, _admin=Depends(require_admin)):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] != "failed":
        raise HTTPException(status_code=400, detail=f"Job is {job['status']}, not failed")
    new_job_id = await job_manager.enqueue(job["source"], job.get("query"))
    _api_logger.info("Admin retry: job %d → new job %d (%s)", job_id, new_job_id, job["source"])
    return _success_response({"new_job_id": new_job_id, "source": job["source"], "query": job.get("query")})


@app.delete("/admin/exports/{job_id}")
async def admin_delete_export(job_id: int, _admin=Depends(require_admin)):
    p = get_export_path(job_id)
    if not p.exists():
        raise HTTPException(status_code=404, detail="Export not found")
    try:
        p.unlink()
        _api_logger.info("Admin deleted export for job %d", job_id)
        return _success_response({"deleted": True, "job_id": job_id})
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete export: {e}")


_frontend_dist = BASE_DIR / "frontend" / "dist"
if _frontend_dist.exists():
    @app.middleware("http")
    async def _serve_frontend(request: Request, call_next):
        path = request.url.path
        if path.startswith("/api") or path.startswith("/stripe/webhook") or path in ("/health", "/docs", "/openapi.json", "/redoc"):
            return await call_next(request)
        static_file = _frontend_dist / path.lstrip("/")
        if static_file.exists() and static_file.is_file():
            return FileResponse(str(static_file))
        index = _frontend_dist / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return await call_next(request)
