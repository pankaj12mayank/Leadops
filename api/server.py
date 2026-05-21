import asyncio
import json
import logging
import logging.handlers
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import patch

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, model_validator

from playwright.async_api import BrowserContext, Playwright, async_playwright

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.json"
CONFIG_BACKUP_PATH = BASE_DIR / "config.backup.json"

_DEFAULT_CONFIG = {
    "browser": {
        "headless": False,
        "timeout": 30000,
        "retry_count": 3,
        "min_delay": 1.0,
        "max_delay": 3.0,
        "concurrency": 1,
        "viewport_width": 1920,
        "viewport_height": 1080,
        "user_agent": "",
        "locale": "en-US",
        "timezone_id": "America/New_York",
        "geolocation": {"latitude": 40.7128, "longitude": -74.006},
    },
    "session": {
        "storage_path": "sessions",
        "state_file": "auth_state.json",
        "auto_save": True,
    },
    "export": {
        "format": "csv",
        "encoding": "utf-8-sig",
    },
    "logging": {
        "level": "INFO",
        "file": "logs/system.log",
        "max_bytes": 10485760,
        "backup_count": 5,
        "format": "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    },
    "paths": {
        "exports": "exports",
        "screenshots": "screenshots",
        "temp": "temp",
        "sessions": "sessions",
    },
}

app = FastAPI(
    title="Lead Extraction API",
    version="1.0.0",
    description="Async API for the Playwright lead extraction system",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_playwright_instance: Optional[Playwright] = None
_browser_context: Optional[BrowserContext] = None
_api_logger: Optional[logging.Logger] = None
_tasks: Dict[str, Dict[str, Any]] = {}
_active_sources: set = set()
_task_refs: Dict[str, asyncio.Task] = {}


def _load_config() -> Dict[str, Any]:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg
    except (FileNotFoundError, json.JSONDecodeError, PermissionError) as e:
        _api_logger and _api_logger.warning("Config load failed (%s), trying backup", e)
        try:
            with open(CONFIG_BACKUP_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            _api_logger.info("Config recovered from backup")
            return cfg
        except Exception:
            _api_logger and _api_logger.warning("Backup also failed, using defaults")
            return dict(_DEFAULT_CONFIG)


def _save_config(config_dict: Dict[str, Any]) -> None:
    tmp_path = CONFIG_PATH.with_suffix(".tmp.json")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(config_dict, f, indent=4, ensure_ascii=False)
        if CONFIG_PATH.exists():
            import shutil
            shutil.copy2(str(CONFIG_PATH), str(CONFIG_BACKUP_PATH))
        tmp_path.replace(CONFIG_PATH)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise


class _SafeRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """RotatingFileHandler that never raises — logs to stderr on failure."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            super().emit(record)
        except Exception:
            try:
                sys.stderr.write(f"Log write failed: {self.baseFilename}\n")
            except Exception:
                pass


def _setup_logger() -> logging.Logger:
    log_dir = BASE_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("api")
    logger.setLevel(logging.DEBUG)

    if logger.handlers:
        return logger

    try:
        cfg = _load_config()
        log_cfg = cfg.get("logging", {})
        log_level = log_cfg.get("level", "INFO")
        log_file_cfg = log_cfg.get("file", "logs/system.log")
        log_format = log_cfg.get(
            "format",
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        )
    except Exception:
        log_level = "INFO"
        log_file_cfg = "logs/system.log"
        log_format = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

    log_file = BASE_DIR / log_file_cfg
    log_file.parent.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(log_format, datefmt="%Y-%m-%d %H:%M:%S")

    rfh = _SafeRotatingFileHandler(
        filename=str(log_file),
        maxBytes=10_485_760,
        backupCount=5,
        encoding="utf-8",
    )
    rfh.setLevel(getattr(logging, log_level.upper(), logging.DEBUG))
    rfh.setFormatter(fmt)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)

    logger.addHandler(rfh)
    logger.addHandler(ch)

    return logger


_api_logger = _setup_logger()


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


def _ensure_export_dirs(cfg: Dict[str, Any]) -> None:
    base = BASE_DIR / cfg.get("paths", {}).get("exports", "exports")
    for src in EXPORT_SOURCES:
        (base / src).mkdir(parents=True, exist_ok=True)


async def _ensure_browser_session() -> bool:
    global _playwright_instance, _browser_context, _api_logger

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
            bypass_csp=True,
            ignore_https_errors=True,
            no_viewport=False,
        )

        state_path = BASE_DIR / cfg["session"]["storage_path"] / cfg["session"]["state_file"]
        if state_path.exists():
            try:
                with open(state_path, "r", encoding="utf-8") as f:
                    storage_state = json.load(f)
                await _browser_context.add_cookies(storage_state.get("cookies", []))
                _api_logger.info("Session state loaded from %s", state_path)
            except Exception as e:
                _api_logger.warning("Failed to load session state: %s", e)

        _api_logger.info("API browser session created successfully")
        return True
    except Exception as e:
        _api_logger.error("Failed to create API browser session: %s", e)
        _playwright_instance = None
        _browser_context = None
        return False


async def _run_task(task_id: str, source: str, coro) -> None:
    global _active_sources

    _tasks[task_id]["status"] = "running"
    _tasks[task_id]["started_at"] = datetime.now(timezone.utc).isoformat()

    try:
        result = await coro
        _tasks[task_id]["status"] = "completed"
        _tasks[task_id]["result"] = result
        _tasks[task_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
        _api_logger.info("Task %s (%s) completed: %s", task_id, source, result)
    except asyncio.CancelledError:
        _tasks[task_id]["status"] = "cancelled"
        _tasks[task_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
        _api_logger.warning("Task %s (%s) was cancelled", task_id, source)
    except Exception as e:
        _tasks[task_id]["status"] = "failed"
        _tasks[task_id]["error"] = str(e)
        _tasks[task_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
        _api_logger.error("Task %s (%s) failed: %s", task_id, source, e)
    finally:
        _active_sources.discard(source)
        _task_refs.pop(source, None)


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
    except Exception:
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


def _scan_export_files() -> List[ExportFile]:
    files: List[ExportFile] = []
    export_dir = BASE_DIR / "exports"
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
            except Exception:
                continue
    return files


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
        except (asyncio.CancelledError, asyncio.TimeoutError):
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
        except Exception:
            pass
        _browser_context = None

    if _playwright_instance:
        try:
            await _playwright_instance.stop()
            _api_logger.info("API Playwright stopped")
        except Exception:
            pass
        _playwright_instance = None

    logging.shutdown()


def _make_input_mock(responses: Dict[str, str]):
    def mock_input(prompt: str = ""):
        prompt_lower = prompt.lower()
        for keyword, value in responses.items():
            if keyword in prompt_lower:
                return value
        return ""
    return mock_input


def _make_confirm_mock(response: str = "y"):
    def mock_input(prompt: str = ""):
        prompt_lower = prompt.lower()
        if "proceed" in prompt_lower or "confirm" in prompt_lower or "y/n" in prompt_lower:
            return response
        return ""
    return mock_input


@app.post("/start/clutch")
async def start_clutch(body: StartQuery):
    from scrapers.clutch import run_clutch_scraper

    cfg = _load_config()

    mock_responses = {
        "search query": body.query,
        "max pages": str(body.max_pages),
    }

    async def scraper_wrapper():
        await _ensure_before_scraper()
        with patch("builtins.input", _make_input_mock(mock_responses)):
            return await run_clutch_scraper(_browser_context, _api_logger, cfg)

    task_id = _start_background("clutch", scraper_wrapper())
    _api_logger.info("Clutch scraper started: query='%s', max_pages=%d", body.query, body.max_pages)
    return {"task_id": task_id, "source": "clutch", "status": "started"}


@app.post("/start/goodfirms")
async def start_goodfirms(body: StartQuery):
    from scrapers.goodfirms import run_goodfirms_scraper

    cfg = _load_config()

    mock_responses = {
        "search query": body.query,
        "max pages": str(body.max_pages),
    }

    async def scraper_wrapper():
        await _ensure_before_scraper()
        with patch("builtins.input", _make_input_mock(mock_responses)):
            return await run_goodfirms_scraper(_browser_context, _api_logger, cfg)

    task_id = _start_background("goodfirms", scraper_wrapper())
    _api_logger.info("GoodFirms scraper started: query='%s', max_pages=%d", body.query, body.max_pages)
    return {"task_id": task_id, "source": "goodfirms", "status": "started"}


@app.post("/start/maps")
async def start_maps(body: StartMapsQuery):
    from scrapers.maps import run_maps_scraper

    cfg = _load_config()

    mock_responses = {
        "search query": body.query,
        "max scroll cycles": str(body.max_cycles),
        "max cycles": str(body.max_cycles),
    }

    async def scraper_wrapper():
        await _ensure_before_scraper()
        with patch("builtins.input", _make_input_mock(mock_responses)):
            return await run_maps_scraper(_browser_context, _api_logger, cfg)

    task_id = _start_background("maps", scraper_wrapper())
    _api_logger.info("Maps scraper started: query='%s', max_cycles=%d", body.query, body.max_cycles)
    return {"task_id": task_id, "source": "maps", "status": "started"}


@app.post("/start/linkedin")
async def start_linkedin(body: StartLinkedinQuery):
    from scrapers.linkedin import run_linkedin_enrichment

    cfg = _load_config()

    csv_path = body.csv_path.strip() if body.csv_path else ""
    if not csv_path:
        csv_path = str(BASE_DIR / "exports" / "linkedin" / "input_companies.csv")

    mock_responses = {
        "path to csv": csv_path,
        "csv with companies": csv_path,
    }

    async def scraper_wrapper():
        await _ensure_before_scraper()
        with patch("builtins.input", _make_input_mock(mock_responses)):
            return await run_linkedin_enrichment(_browser_context, _api_logger, cfg)

    task_id = _start_background("linkedin", scraper_wrapper())
    _api_logger.info("Linkedin enrichment started: csv_path='%s'", csv_path)
    return {"task_id": task_id, "source": "linkedin", "status": "started"}


@app.post("/stop/{source}")
async def stop_scraper(source: str):
    if source not in _active_sources:
        raise HTTPException(status_code=404, detail=f"No running task for source '{source}'")

    task = _task_refs.get(source)
    if task and not task.done():
        task.cancel()
        _api_logger.info("Task '%s' cancellation requested", source)
        return {"source": source, "status": "cancelling"}

    _active_sources.discard(source)
    _task_refs.pop(source, None)
    return {"source": source, "status": "cancelled"}


@app.post("/merge")
async def start_merge():
    from scrapers.merge import run_merge_engine

    async def merge_wrapper():
        with patch("builtins.input", _make_confirm_mock("y")):
            return await run_merge_engine(_api_logger)

    task_id = _start_background("merge", merge_wrapper())
    _api_logger.info("Merge started")
    return {"task_id": task_id, "source": "merge", "status": "started"}


@app.get("/status", response_model=Dict[str, Any])
async def get_status(task_id: Optional[str] = Query(None)):
    if task_id:
        info = _tasks.get(task_id)
        if not info:
            raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
        return {"task": info}

    return {
        "active_sources": list(sorted(_active_sources)),
        "total_tasks": len(_tasks),
        "tasks": list(_tasks.values()),
    }


import re

_LOG_PATTERN = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \| (\w+) +\|\s*(\S+)\s*\| (.+)$"
)


def _parse_log_line(lineno: int, raw: str) -> Dict[str, Any]:
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


@app.get("/logs", response_model=Dict[str, Any])
async def get_logs(
    lines: int = Query(200, ge=1, le=5000),
    source: Optional[str] = Query(None),
    reverse: bool = Query(True),
):
    log_file = BASE_DIR / "logs" / "system.log"
    if not log_file.exists():
        return {"file": "logs/system.log", "entries": [], "total_lines": 0}

    try:
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
        total = len(all_lines)

        tail = all_lines[-lines:] if lines < total else all_lines
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

        return {
            "file": "logs/system.log",
            "total_lines": total,
            "returned": len(entries),
            "entries": entries,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read log file: {e}")


@app.get("/exports", response_model=Dict[str, Any])
async def get_exports():
    files = _scan_export_files()
    groups: Dict[str, list] = {}
    for f in files:
        groups.setdefault(f.source, []).append(f.model_dump())

    total_size = sum(f.size_bytes for f in files)
    return {
        "total_files": len(files),
        "total_size_bytes": total_size,
        "total_size_kb": round(total_size / 1024, 1),
        "sources": list(groups.keys()),
        "files": files,
    }


@app.get("/download/{file_path:path}")
async def download_export(file_path: str):
    full_path = (BASE_DIR / file_path).resolve()
    if not str(full_path).startswith(str(BASE_DIR.resolve())):
        raise HTTPException(status_code=403, detail="Path traversal denied")
    if not full_path.exists() or not full_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    media_type = "text/csv" if full_path.suffix == ".csv" else "application/octet-stream"
    return FileResponse(
        path=str(full_path),
        media_type=media_type,
        filename=full_path.name,
        headers={"Content-Disposition": f'attachment; filename="{full_path.name}"'},
    )


@app.delete("/export/{file_path:path}")
async def delete_export(file_path: str):
    full_path = (BASE_DIR / file_path).resolve()
    if not str(full_path).startswith(str(BASE_DIR.resolve())):
        raise HTTPException(status_code=403, detail="Path traversal denied")
    if not full_path.exists() or not full_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    try:
        full_path.unlink()
        _api_logger.info("Deleted export file: %s", file_path)
        return {"deleted": True, "path": file_path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete file: {e}")


@app.get("/settings", response_model=SystemConfig)
async def get_settings():
    try:
        cfg = _load_config()
        return SystemConfig(**cfg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read settings: {e}")


@app.post("/settings", response_model=SystemConfig)
async def update_settings(body: SystemConfig):
    try:
        config_dict = body.model_dump()
        _save_config(config_dict)
        _api_logger.info("Settings updated by user")
        return body
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save settings: {e}")


@app.get("/health")
async def health():
    session_ok = _browser_context is not None
    return {
        "status": "ok",
        "browser_session": "active" if session_ok else "inactive",
        "active_tasks": len(_active_sources),
    }
