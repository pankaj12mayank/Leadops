import asyncio
import json
import logging
import os
import re
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from playwright.async_api import BrowserContext, Playwright, async_playwright
from playwright.async_api import TimeoutError as PlaywrightTimeout
from pydantic import BaseModel, model_validator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

import config as cfg_mod
from scrapers.base import NavigationError, ScraperError
from session_encrypt import decrypt_state, make_key_from_secret

BASE_DIR = cfg_mod.BASE_DIR
CONFIG_PATH = cfg_mod.CONFIG_PATH

app = FastAPI(
    title="Lead Extraction API",
    version="1.0.0",
    description="Async API for the Playwright lead extraction system",
)

limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


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


@app.exception_handler(HTTPException)
async def _http_exception_handler(request: Request, exc: HTTPException):
    return _error_response(exc.status_code, "HTTP_ERROR", exc.detail)


@app.exception_handler(Exception)
async def _generic_exception_handler(request: Request, exc: Exception):
    _api_logger.exception("Unhandled exception: %s", exc)
    return _error_response(500, "INTERNAL_ERROR", "An unexpected error occurred")


@app.middleware("http")
async def _rewrite_api_prefix(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api"):
        remaining = path[4:] or "/"
        request.scope["path"] = remaining
        rp = request.scope.get("raw_path", b"")
        if rp:
            request.scope["raw_path"] = rp[4:] or b"/"
    return await call_next(request)


@app.middleware("http")
async def _timeout_middleware(request: Request, call_next):
    try:
        return await asyncio.wait_for(call_next(request), timeout=120.0)
    except TimeoutError:
        return _error_response(408, "TIMEOUT", "Request timed out")


_playwright_instance: Playwright | None = None
_browser_context: BrowserContext | None = None
_api_logger: logging.Logger | None = None
_tasks: dict[str, dict[str, Any]] = {}
_active_sources: set = set()
_task_refs: dict[str, asyncio.Task] = {}
_ws_clients: list[WebSocket] = []
_browser_lock = asyncio.Lock()
_FILE_CACHE: dict[str, Any] = {"ts": 0, "data": []}
_FILE_CACHE_TTL = 5.0


async def _broadcast_status() -> None:
    status = {
        "active_sources": list(sorted(_active_sources)),
        "total_tasks": len(_tasks),
        "tasks": list(_tasks.values()),
    }
    stale: list[WebSocket] = []
    for ws in _ws_clients:
        try:
            await ws.send_json(status)
        except Exception as e:
            _api_logger.debug("WebSocket send failed: %s", e)
            stale.append(ws)
    for ws in stale:
        try:
            _ws_clients.remove(ws)
        except ValueError:
            pass
    if stale:
        _api_logger.debug("Cleaned up %d stale WebSocket clients", len(stale))


def _load_config() -> dict[str, Any]:
    return cfg_mod.load_config()


_CONFIG_CACHE: dict[str, Any] = {"ts": 0.0, "data": None}
_CONFIG_CACHE_TTL = 5.0


def _get_config() -> dict[str, Any]:
    now = time.time()
    if now - _CONFIG_CACHE["ts"] < _CONFIG_CACHE_TTL and _CONFIG_CACHE["data"] is not None:
        return _CONFIG_CACHE["data"]
    cfg = _load_config()
    _CONFIG_CACHE["ts"] = now
    _CONFIG_CACHE["data"] = cfg
    return cfg


def _invalidate_config_cache() -> None:
    _CONFIG_CACHE["ts"] = 0.0


_startup_cfg = _load_config()
_cors_origins = _startup_cfg.get("api", {}).get("allowed_origins", ["http://localhost:5173", "http://localhost:4173"])
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _api_key_auth(request: Request, call_next):
    cfg = _get_config()
    api_key = cfg.get("api", {}).get("api_key", "")
    if not api_key:
        return await call_next(request)
    if request.url.path in ("/health", "/docs", "/openapi.json", "/redoc"):
        return await call_next(request)
    auth = request.headers.get("X-API-Key", "")
    if auth != api_key:
        return _error_response(403, "UNAUTHORIZED", "Invalid or missing API key")
    return await call_next(request)


def _save_config(config_dict: dict[str, Any]) -> None:
    cfg_mod.save_config(config_dict)


_api_logger = cfg_mod.setup_logging("api")


class GeoLocation(BaseModel):
    latitude: float = 40.7128
    longitude: float = -74.0060


class BrowserSettings(BaseModel):
    headless: bool = False
    timeout: int = 30000
    retry_count: int = 3
    min_delay: float = 1.0
    max_delay: float = 3.0
    concurrency: int = 1
    viewport_width: int = 1920
    viewport_height: int = 1080
    user_agent: str = ""
    locale: str = "en-US"
    timezone_id: str = "America/New_York"
    geolocation: GeoLocation = GeoLocation()

    @model_validator(mode="after")
    def _validate_ranges(self) -> "BrowserSettings":
        if self.timeout < 1000:
            raise ValueError("timeout must be at least 1000ms")
        if self.retry_count < 0:
            raise ValueError("retry_count cannot be negative")
        if self.min_delay < 0:
            raise ValueError("min_delay cannot be negative")
        if self.max_delay <= self.min_delay:
            raise ValueError("max_delay must be greater than min_delay")
        if self.concurrency < 1:
            raise ValueError("concurrency must be at least 1")
        if self.viewport_width < 320:
            raise ValueError("viewport_width must be at least 320")
        if self.viewport_height < 240:
            raise ValueError("viewport_height must be at least 240")
        return self


class SessionSettingsConfig(BaseModel):
    storage_path: str = "sessions"
    state_file: str = "auth_state.json"
    auto_save: bool = True


class ExportSettingsConfig(BaseModel):
    format: str = "csv"
    encoding: str = "utf-8-sig"


class LoggingSettingsConfig(BaseModel):
    level: str = "INFO"
    file: str = "logs/system.log"
    max_bytes: int = 10485760
    backup_count: int = 5
    format: str = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


class PathsConfig(BaseModel):
    exports: str = "exports"
    screenshots: str = "screenshots"
    temp: str = "temp"
    sessions: str = "sessions"


class SystemConfig(BaseModel):
    browser: BrowserSettings = BrowserSettings()
    session: SessionSettingsConfig = SessionSettingsConfig()
    export: ExportSettingsConfig = ExportSettingsConfig()
    logging: LoggingSettingsConfig = LoggingSettingsConfig()
    paths: PathsConfig = PathsConfig()


class StartQuery(BaseModel):
    query: str
    max_pages: int = 5


class StartMapsQuery(BaseModel):
    query: str
    max_cycles: int = 30


class StartLinkedinQuery(BaseModel):
    csv_path: str = ""
    max_confirm: bool = True


class ExportFile(BaseModel):
    path: str
    filename: str
    size_bytes: int
    source: str
    last_modified: str
    type: str = "raw"


EXPORT_SOURCES = ["clutch", "goodfirms", "maps", "linkedin", "merged"]


def _ensure_export_dirs(cfg: dict[str, Any]) -> None:
    base = BASE_DIR / cfg.get("paths", {}).get("exports", "exports")
    for src in EXPORT_SOURCES:
        (base / src).mkdir(parents=True, exist_ok=True)


async def _check_browser_health() -> bool:
    if _browser_context is None:
        return False
    try:
        pages = _browser_context.pages
        try:
            _ = len(pages)
        except (AttributeError, TypeError):
            return False
        if not pages:
            await _browser_context.new_page()
        return True
    except (TimeoutError, PlaywrightTimeout, OSError) as e:
        _api_logger.warning("Browser health check failed: %s", e)
        return False


async def _ensure_browser_session() -> bool:
    global _playwright_instance, _browser_context, _api_logger

    if _browser_context is not None:
        if await _check_browser_health():
            return True
        _api_logger.warning("Browser session unhealthy, restarting...")
        try:
            await _browser_context.close()
        except (TimeoutError, PlaywrightTimeout, OSError):
            pass
        _browser_context = None
        if _playwright_instance:
            try:
                await _playwright_instance.stop()
            except (TimeoutError, PlaywrightTimeout, OSError):
                pass
            _playwright_instance = None

    async with _browser_lock:
        if _browser_context is not None:
            return True
        try:
            cfg = _load_config()
            _ensure_export_dirs(cfg)
            _api_logger.info("Creating browser session for API...")
            _playwright_instance = await async_playwright().start()
            geo = cfg["browser"].get("geolocation", {})

            _browser_context = await _playwright_instance.chromium.launch_persistent_context(
                user_data_dir=str(BASE_DIR / cfg["session"]["storage_path"] / "api_profile"),
                headless=cfg["browser"]["headless"],
                viewport={"width": cfg["browser"]["viewport_width"], "height": cfg["browser"]["viewport_height"]},
                user_agent=cfg["browser"]["user_agent"],
                locale=cfg["browser"]["locale"],
                timezone_id=cfg["browser"]["timezone_id"],
                geolocation={"latitude": geo.get("latitude", 40.7128), "longitude": geo.get("longitude", -74.0060)},
                permissions=["geolocation"],
                bypass_csp=cfg["browser"].get("bypass_csp", False),
                ignore_https_errors=cfg["browser"].get("ignore_https_errors", False),
                no_viewport=False,
            )

            state_path = BASE_DIR / cfg["session"]["storage_path"] / cfg["session"]["state_file"]
            if state_path.exists():
                try:
                    raw = state_path.read_text(encoding="utf-8")
                    enc_key_secret = cfg_mod.get_session_encrypt_key()
                    storage_state = None
                    if enc_key_secret:
                        key = make_key_from_secret(enc_key_secret)
                        if key:
                            storage_state = decrypt_state(raw, key)
                    if storage_state is None:
                        storage_state = json.loads(raw)
                    await _browser_context.add_cookies(storage_state.get("cookies", []))
                    _api_logger.info("Session state loaded from %s", state_path)
                except (json.JSONDecodeError, KeyError, OSError) as e:
                    _api_logger.warning("Failed to load session state: %s", e)

            _api_logger.info("API browser session created successfully")
            return True
        except (TimeoutError, PlaywrightTimeout, OSError) as e:
            _api_logger.error("Failed to create API browser session: %s", e)
            _playwright_instance = None
            _browser_context = None
            return False


async def _run_task(task_id: str, source: str, coro) -> None:
    global _active_sources

    _tasks[task_id]["status"] = "running"
    _tasks[task_id]["started_at"] = datetime.now(UTC).isoformat()
    await _broadcast_status()

    try:
        result = await coro
        _tasks[task_id]["status"] = "completed"
        _tasks[task_id]["result"] = result
        _tasks[task_id]["completed_at"] = datetime.now(UTC).isoformat()
        _api_logger.info("Task %s (%s) completed: %s", task_id, source, result)
    except asyncio.CancelledError:
        _tasks[task_id]["status"] = "cancelled"
        _tasks[task_id]["completed_at"] = datetime.now(UTC).isoformat()
        _api_logger.warning("Task %s (%s) was cancelled", task_id, source)
    except Exception as e:
        _tasks[task_id]["status"] = "failed"
        _tasks[task_id]["error"] = str(e)
        _tasks[task_id]["completed_at"] = datetime.now(UTC).isoformat()
        _api_logger.error("Task %s (%s) failed: %s", task_id, source, e)
    finally:
        _active_sources.discard(source)
        _task_refs.pop(source, None)
        await _broadcast_status()


MAX_TASK_HISTORY = 100


def _trim_task_history() -> None:
    if len(_tasks) <= MAX_TASK_HISTORY:
        return
    terminal = {k: v for k, v in _tasks.items() if v["status"] in ("completed", "failed", "cancelled")}
    if len(terminal) <= MAX_TASK_HISTORY:
        return
    sorted_keys = sorted(terminal.keys(), key=lambda k: terminal[k].get("completed_at") or "")
    for old_key in sorted_keys[: len(sorted_keys) - MAX_TASK_HISTORY]:
        _tasks.pop(old_key, None)


def _start_background(name: str, coro) -> str:
    if name in _active_sources:
        raise HTTPException(status_code=409, detail=f"Task '{name}' is already running")

    task_id = str(uuid.uuid4())[:8]
    _tasks[task_id] = {
        "task_id": task_id,
        "source": name,
        "status": "pending",
        "started_at": None,
        "completed_at": None,
        "result": None,
        "error": None,
    }
    _active_sources.add(name)
    try:
        task = asyncio.create_task(_run_task(task_id, name, coro))
    except (RuntimeError, asyncio.CancelledError):
        _active_sources.discard(name)
        _tasks.pop(task_id, None)
        raise
    _task_refs[name] = task
    _trim_task_history()
    return task_id


async def _ensure_before_scraper() -> bool:
    ok = await _ensure_browser_session()
    if not ok:
        raise HTTPException(status_code=503, detail="Failed to create browser session")
    if _browser_context is None:
        raise HTTPException(status_code=503, detail="Browser context not available")
    return True


def _scan_export_files() -> list[ExportFile]:
    now = time.time()
    if now - _FILE_CACHE["ts"] < _FILE_CACHE_TTL:
        return _FILE_CACHE["data"]
    files: list[ExportFile] = []
    export_dir = BASE_DIR / "exports"
    if not export_dir.exists():
        _FILE_CACHE["ts"] = now
        _FILE_CACHE["data"] = files
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
                        last_modified=datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
                        type=_export_type(source_name, fpath.name),
                    )
                )
            except (OSError, PermissionError):
                continue
    _FILE_CACHE["ts"] = time.time()
    _FILE_CACHE["data"] = files
    return files


def _invalidate_file_cache() -> None:
    _FILE_CACHE["ts"] = 0


def _export_type(source: str, filename: str) -> str:
    if source == "merged":
        return "merged"
    return "raw"


async def _cancel_all_tasks() -> None:
    pending = [(src, t) for src, t in _task_refs.items() if not t.done()]
    if not pending:
        return
    _api_logger.warning("Cancelling %d running tasks during shutdown", len(pending))
    for src, t in pending:
        t.cancel()
    await asyncio.sleep(0)
    for src, t in pending:
        try:
            await asyncio.wait_for(t, timeout=10.0)
        except (TimeoutError, asyncio.CancelledError):
            _api_logger.warning("Task '%s' did not finish within timeout", src)


@app.on_event("shutdown")
async def _on_shutdown() -> None:
    global _playwright_instance, _browser_context, _api_logger

    _api_logger.info("API server shutting down")
    await _cancel_all_tasks()

    if _browser_context:
        try:
            await _browser_context.close()
            _api_logger.info("API browser context closed")
        except (TimeoutError, PlaywrightTimeout, OSError):
            pass
        _browser_context = None

    if _playwright_instance:
        try:
            await _playwright_instance.stop()
            _api_logger.info("API Playwright stopped")
        except (TimeoutError, PlaywrightTimeout, OSError):
            pass
        _playwright_instance = None

    logging.shutdown()


@app.post("/start/clutch")
@limiter.limit("10/minute")
async def start_clutch(request: Request, body: StartQuery):
    from scrapers.clutch import run_clutch_scraper

    cfg = _get_config()

    async def scraper_wrapper():
        await _ensure_before_scraper()
        return await run_clutch_scraper(_browser_context, _api_logger, cfg, body.query, body.max_pages)

    task_id = _start_background("clutch", scraper_wrapper())
    _api_logger.info("Clutch scraper started: query='%s', max_pages=%d", body.query, body.max_pages)
    return _success_response({"task_id": task_id, "source": "clutch", "status": "started"})


@app.post("/start/goodfirms")
@limiter.limit("10/minute")
async def start_goodfirms(request: Request, body: StartQuery):
    from scrapers.goodfirms import run_goodfirms_scraper

    cfg = _get_config()

    async def scraper_wrapper():
        await _ensure_before_scraper()
        return await run_goodfirms_scraper(_browser_context, _api_logger, cfg, body.query, body.max_pages)

    task_id = _start_background("goodfirms", scraper_wrapper())
    _api_logger.info("GoodFirms scraper started: query='%s', max_pages=%d", body.query, body.max_pages)
    return _success_response({"task_id": task_id, "source": "goodfirms", "status": "started"})


@app.post("/start/maps")
@limiter.limit("10/minute")
async def start_maps(request: Request, body: StartMapsQuery):
    from scrapers.maps import run_maps_scraper

    cfg = _get_config()

    async def scraper_wrapper():
        await _ensure_before_scraper()
        return await run_maps_scraper(_browser_context, _api_logger, cfg, body.query, body.max_cycles)

    task_id = _start_background("maps", scraper_wrapper())
    _api_logger.info("Maps scraper started: query='%s', max_cycles=%d", body.query, body.max_cycles)
    return _success_response({"task_id": task_id, "source": "maps", "status": "started"})


@app.post("/start/linkedin")
@limiter.limit("10/minute")
async def start_linkedin(request: Request, body: StartLinkedinQuery):
    from scrapers.linkedin import run_linkedin_enrichment

    cfg = _get_config()

    csv_path = body.csv_path.strip() if body.csv_path else ""
    if not csv_path:
        csv_path = str(BASE_DIR / "exports" / "linkedin" / "input_companies.csv")

    async def scraper_wrapper():
        await _ensure_before_scraper()
        return await run_linkedin_enrichment(_browser_context, _api_logger, cfg, Path(csv_path))

    task_id = _start_background("linkedin", scraper_wrapper())
    _api_logger.info("Linkedin enrichment started: csv_path='%s'", csv_path)
    return _success_response({"task_id": task_id, "source": "linkedin", "status": "started"})


@app.post("/stop/{source}")
@limiter.limit("30/minute")
async def stop_scraper(request: Request, source: str):
    if source not in _active_sources:
        raise HTTPException(status_code=404, detail=f"No running task for source '{source}'")

    task = _task_refs.get(source)
    if task and not task.done():
        task.cancel()
        _api_logger.info("Task '%s' cancellation requested", source)
        return _success_response({"source": source, "status": "cancelling"})

    _active_sources.discard(source)
    _task_refs.pop(source, None)
    return _success_response({"source": source, "status": "cancelled"})


@app.post("/merge")
@limiter.limit("10/minute")
async def start_merge(request: Request):
    from scrapers.merge import run_merge_engine

    async def merge_wrapper():
        return await run_merge_engine(_api_logger, confirm=True)

    task_id = _start_background("merge", merge_wrapper())
    _api_logger.info("Merge started")
    return _success_response({"task_id": task_id, "source": "merge", "status": "started"})


@app.post("/cleanup")
@limiter.limit("10/minute")
async def trigger_cleanup(request: Request):
    from scrapers.merge import cleanup_old_exports

    cfg = _get_config()
    retention = cfg.get("export", {}).get("retention_days", 30)
    max_size = cfg.get("export", {}).get("max_size_mb", 500)
    deleted = cleanup_old_exports(_api_logger, retention_days=retention, max_size_mb=max_size)
    _api_logger.info("Cleanup removed %d files", deleted)
    return _success_response({"deleted_files": deleted, "retention_days": retention})


@app.get("/status", response_model=dict[str, Any])
async def get_status(task_id: str | None = Query(None)):
    if task_id:
        info = _tasks.get(task_id)
        if not info:
            raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
        return _success_response({"task": info})

    return _success_response({
        "active_sources": list(sorted(_active_sources)),
        "total_tasks": len(_tasks),
        "tasks": list(_tasks.values()),
    })


_LOG_PATTERN = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \| (\w+) +\|\s*(\S+)\s*\| (.+)$"
)


def _parse_log_line(lineno: int, raw: str) -> dict[str, Any]:
    m = _LOG_PATTERN.match(raw)
    if m:
        return {
            "lineno": lineno,
            "timestamp": m.group(1),
            "level": m.group(2),
            "name": m.group(3),
            "message": m.group(4),
            "raw": raw,
        }
    return {
        "lineno": lineno,
        "timestamp": None,
        "level": None,
        "name": None,
        "message": raw,
        "raw": raw,
    }


@app.get("/logs", response_model=dict[str, Any])
async def get_logs(
    lines: int = Query(200, ge=1, le=5000),
    source: str | None = Query(None),
    reverse: bool = Query(True),
):
    log_file = BASE_DIR / "logs" / "system.log"
    if not log_file.exists():
        return _success_response({"file": "logs/system.log", "entries": [], "total_lines": 0})

    try:
        total = 0
        tail: list[str] = []
        chunk_size = 8192
        with open(log_file, encoding="utf-8", errors="replace") as f:
            f.seek(0, 2)
            file_size = f.tell()
            pos = file_size
            buf = ""
            while pos > 0 and len(tail) < lines:
                read_size = min(chunk_size, pos)
                pos -= read_size
                f.seek(pos)
                chunk = f.read(read_size)
                buf = chunk + buf
                tail = [ln for ln in buf.split("\n") if ln][-lines:]
                total = buf.count("\n") + pos // chunk_size * 200
            total = file_size // 80 if total < len(tail) else total

        start_lineno = total - len(tail) + 1
        entries = [
            _parse_log_line(start_lineno + i, ln.rstrip("\n"))
            for i, ln in enumerate(tail)
        ]

        if source:
            source_lower = source.lower()
            entries = [
                e for e in entries
                if (e["name"] and e["name"].lower() == source_lower)
                or (e["message"] and source_lower in e["message"].lower())
            ]

        if reverse:
            entries.reverse()

        return _success_response({
            "file": "logs/system.log",
            "total_lines": total,
            "returned": len(entries),
            "entries": entries,
        })
    except (OSError, PermissionError) as e:
        raise HTTPException(status_code=500, detail=f"Failed to read log file: {e}")


@app.get("/exports", response_model=dict[str, Any])
async def get_exports():
    files = _scan_export_files()
    groups: dict[str, list] = {}
    for f in files:
        groups.setdefault(f.source, []).append(f.model_dump())

    total_size = sum(f.size_bytes for f in files)
    return _success_response({
        "total_files": len(files),
        "total_size_bytes": total_size,
        "total_size_kb": round(total_size / 1024, 1),
        "sources": list(groups.keys()),
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
    return FileResponse(
        path=str(full_path),
        media_type=media_type,
        filename=full_path.name,
        headers={"Content-Disposition": f'attachment; filename="{full_path.name}"'},
    )


@app.delete("/export/{file_path:path}")
async def delete_export(file_path: str):
    full_path = _validate_file_path(file_path)

    try:
        full_path.unlink()
        _invalidate_file_cache()
        _api_logger.info("Deleted export file: %s", file_path)
        return _success_response({"deleted": True, "path": file_path})
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete file: {e}")


@app.get("/settings", response_model=SystemConfig)
async def get_settings():
    try:
        cfg = _load_config()
        return _success_response(SystemConfig(**cfg).model_dump())
    except (ValueError, TypeError, KeyError) as e:
        raise HTTPException(status_code=500, detail=f"Failed to read settings: {e}")


@app.post("/settings", response_model=SystemConfig)
@limiter.limit("30/minute")
async def update_settings(request: Request, body: SystemConfig):
    try:
        config_dict = body.model_dump()
        _save_config(config_dict)
        _invalidate_config_cache()
        _api_logger.info("Settings updated by user")
        return _success_response(body.model_dump())
    except (OSError, PermissionError) as e:
        raise HTTPException(status_code=500, detail=f"Failed to save settings: {e}")


@app.websocket("/ws/status")
async def ws_status(websocket: WebSocket):
    await websocket.accept()
    _ws_clients.append(websocket)
    try:
        await websocket.send_json({
            "active_sources": list(sorted(_active_sources)),
            "total_tasks": len(_tasks),
            "tasks": list(_tasks.values()),
        })
        while True:
            try:
                await websocket.receive_text()
            except WebSocketDisconnect:
                break
    except (WebSocketDisconnect, ConnectionError):
        pass
    finally:
        try:
            _ws_clients.remove(websocket)
        except ValueError:
            pass


@app.get("/health")
async def health():
    session_ok = _browser_context is not None
    exports_dir = BASE_DIR / "exports"
    logs_dir = BASE_DIR / "logs"
    return _success_response({
        "status": "ok",
        "version": "1.0.0",
        "browser_session": "active" if session_ok else "inactive",
        "active_tasks": len(_active_sources),
        "exports_writable": os.access(str(exports_dir), os.W_OK) if exports_dir.exists() else False,
        "logs_writable": os.access(str(logs_dir), os.W_OK) if logs_dir.exists() else False,
        "python_version": sys.version.split()[0],
    })


class _CachedStaticFiles(StaticFiles):
    async def file_response(self, full_path, stat_result, scope, status_code=200):
        resp = await super().file_response(full_path, stat_result, scope, status_code)
        url_path = scope.get("path", "")
        if re.search(r"[.-][a-f0-9]{8,}\.(?:js|css|png|jpe?g|svg|woff2?|ico)$", url_path, re.IGNORECASE):
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            resp.headers["Cache-Control"] = "no-cache"
        return resp


_frontend_dist = BASE_DIR / "frontend" / "dist"
if _frontend_dist.exists():
    app.mount(
        "/",
        _CachedStaticFiles(directory=str(_frontend_dist), html=True),
        name="frontend",
    )
