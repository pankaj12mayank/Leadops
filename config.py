import json
import logging
import logging.handlers
import os as _os
import shutil
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

_env_path = Path(__file__).resolve().parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)


def _env(key: str, default: str = "") -> str:
    return _os.environ.get(key, default)

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
CONFIG_BACKUP_PATH = BASE_DIR / "config.backup.json"

DEFAULT_CONFIG: dict[str, Any] = {
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
        "bypass_csp": False,
        "ignore_https_errors": False,
        "connection_timeout": 30,
        "keep_alive": True,
    },
    "session": {
        "storage_path": "sessions",
        "state_file": "auth_state.json",
        "auto_save": True,
    },
    "scraping": {
        "max_pages": 5,
        "max_scroll_cycles": 30,
        "scroll_steps": 10,
        "scroll_delay": 0.35,
        "consecutive_empty_scrolls": 5,
        "extraction_retries": 2,
        "page_delay_multiplier": 2.0,
    },
    "export": {
        "format": "csv",
        "encoding": "utf-8-sig",
        "retention_days": 30,
        "max_size_mb": 500,
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
    "api": {
        "api_key": "",
        "allowed_origins": ["http://localhost:5173", "http://localhost:4173"],
        "host": "127.0.0.1",
        "port": 8000,
    },
}

REQUIRED_DIRS = [
    BASE_DIR / "sessions",
    BASE_DIR / "exports" / "clutch",
    BASE_DIR / "exports" / "goodfirms",
    BASE_DIR / "exports" / "linkedin",
    BASE_DIR / "exports" / "maps",
    BASE_DIR / "exports" / "merged",
    BASE_DIR / "logs",
    BASE_DIR / "screenshots",
    BASE_DIR / "temp",
]


def ensure_directories() -> None:
    for d in REQUIRED_DIRS:
        d.mkdir(parents=True, exist_ok=True)


def load_config() -> dict[str, Any]:
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
        result = _merge_with_defaults(cfg)
    except (FileNotFoundError, json.JSONDecodeError, PermissionError):
        try:
            with open(CONFIG_BACKUP_PATH, encoding="utf-8") as f:
                cfg = json.load(f)
            result = _merge_with_defaults(cfg)
        except (FileNotFoundError, json.JSONDecodeError, PermissionError, OSError):
            result = dict(DEFAULT_CONFIG)

    api_key = _env("API_KEY")
    cors_origins = _env("CORS_ORIGINS")
    host = _env("API_HOST")
    port = _env("API_PORT")
    if api_key:
        result.setdefault("api", {})["api_key"] = api_key
    if cors_origins:
        result.setdefault("api", {})["allowed_origins"] = [o.strip() for o in cors_origins.split(",")]
    if host:
        result.setdefault("api", {})["host"] = host
    if port and port.isdigit():
        port_val = int(port)
        if 1 <= port_val <= 65535:
            result.setdefault("api", {})["port"] = port_val
    return result


def get_session_encrypt_key() -> str:
    return _env("SESSION_ENCRYPT_KEY")


def save_config(config_dict: dict[str, Any]) -> None:
    tmp_path = CONFIG_PATH.with_suffix(".tmp.json")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(config_dict, f, indent=4, ensure_ascii=False)
        tmp_path.replace(CONFIG_PATH)
        shutil.copy2(str(CONFIG_PATH), str(CONFIG_BACKUP_PATH))
    except OSError:
        if tmp_path.exists():
            tmp_path.unlink()
        raise


def _merge_with_defaults(cfg: dict[str, Any]) -> dict[str, Any]:
    merged = dict(DEFAULT_CONFIG)
    for section, values in cfg.items():
        if section in merged and isinstance(merged[section], dict) and isinstance(values, dict):
            merged[section].update(values)
        else:
            merged[section] = values
    return merged


class SafeRotatingFileHandler(logging.handlers.RotatingFileHandler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            super().emit(record)
        except Exception:
            try:
                sys.stderr.write(f"Log write failed: {self.baseFilename}\n")
            except OSError:
                pass


def setup_logging(name: str = "lead_system") -> logging.Logger:
    log_dir = BASE_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    if logger.handlers:
        return logger

    try:
        cfg = load_config()
        log_cfg = cfg.get("logging", {})
        log_level = log_cfg.get("level", "INFO")
        log_file_cfg = log_cfg.get("file", "logs/system.log")
        log_format = log_cfg.get("format", "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
    except (KeyError, ValueError, TypeError, OSError):
        log_level = "INFO"
        log_file_cfg = "logs/system.log"
        log_format = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

    log_file = BASE_DIR / log_file_cfg
    log_file.parent.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(log_format, datefmt="%Y-%m-%d %H:%M:%S")

    rfh = SafeRotatingFileHandler(
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
