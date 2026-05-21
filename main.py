import asyncio
import json
import logging
import logging.handlers
import os
import random
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
from playwright.async_api import (
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

from scrapers.clutch import run_clutch_scraper
from scrapers.goodfirms import run_goodfirms_scraper
from scrapers.maps import run_maps_scraper
from scrapers.linkedin import run_linkedin_enrichment
from scrapers.merge import run_merge_engine

BASE_DIR = Path(__file__).resolve().parent
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

_playwright_instance: Optional[Playwright] = None
_browser_context: Optional[BrowserContext] = None
_logger: Optional[logging.Logger] = None


def _ensure_directories() -> None:
    for d in REQUIRED_DIRS:
        d.mkdir(parents=True, exist_ok=True)


def _load_config() -> Dict[str, Any]:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg
    except (FileNotFoundError, json.JSONDecodeError, PermissionError) as e:
        if _logger:
            _logger.warning("Config load failed (%s), trying backup", e)
        try:
            with open(CONFIG_BACKUP_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            if _logger:
                _logger.info("Config recovered from backup")
            return cfg
        except Exception:
            if _logger:
                _logger.warning("Backup also failed, using defaults")
            return dict(_DEFAULT_CONFIG)


class _SafeRotatingFileHandler(logging.handlers.RotatingFileHandler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            super().emit(record)
        except Exception:
            try:
                sys.stderr.write(f"Log write failed: {self.baseFilename}\n")
            except Exception:
                pass


def _setup_logging() -> logging.Logger:
    log_dir = BASE_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("lead_system")
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


async def _random_delay(min_sec: float, max_sec: float) -> None:
    await asyncio.sleep(random.uniform(min_sec, max_sec))


async def _safe_goto(page: Page, url: str, cfg: Dict[str, Any], retries: int = None) -> bool:
    if retries is None:
        retries = cfg["browser"]["retry_count"]
    timeout = cfg["browser"]["timeout"]

    for attempt in range(1, retries + 1):
        try:
            await page.goto(url, timeout=timeout, wait_until="domcontentloaded")
            await page.wait_for_load_state("networkidle", timeout=timeout)
            return True
        except Exception as e:
            _logger.warning("Navigation attempt %d/%d failed for %s: %s", attempt, retries, url, e)
            if attempt < retries:
                await asyncio.sleep(attempt * 2)
    _logger.error("All %d navigation attempts failed for %s", retries, url)
    return False


async def _save_screenshot(page: Page, label: str = "screenshot") -> Optional[Path]:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_label = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in label)
    path = BASE_DIR / "screenshots" / f"{ts}_{safe_label}.png"
    try:
        await page.screenshot(path=str(path), full_page=True)
        _logger.info("Screenshot saved: %s", path)
        return path
    except Exception as e:
        _logger.error("Failed to save screenshot: %s", e)
        return None


_export_df_logger = logging.getLogger("main.export")


def _export_dataframe(df: pd.DataFrame, filename: str, export_format: str) -> Optional[Path]:
    if df.empty:
        _export_df_logger.warning("DataFrame is empty, skipping export for %s", filename)
        return None
    safe_name = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in filename)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    ext = export_format.strip().lower()
    known = {"csv", "json", "parquet", "xlsx"}
    if ext not in known:
        _export_df_logger.warning("Unknown export format '%s', falling back to csv", ext)
        ext = "csv"
    out = BASE_DIR / "exports" / "merged" / f"{ts}_{safe_name}.{ext}"
    try:
        if ext == "csv":
            df.to_csv(out, index=False, encoding="utf-8-sig")
        elif ext == "json":
            df.to_json(out, orient="records", indent=2, force_ascii=False)
        elif ext == "parquet":
            df.to_parquet(out, index=False)
        else:
            try:
                df.to_excel(out, index=False)
            except Exception as xl_err:
                _export_df_logger.error("XLSX export failed for %s: %s, falling back to CSV", filename, xl_err)
                ext = "csv"
                out = out.with_suffix(".csv")
                df.to_csv(out, index=False, encoding="utf-8-sig")
        _export_df_logger.info("Exported %d rows to %s", len(df), out)
        return out
    except Exception as e:
        _export_df_logger.error("Export failed for %s: %s", filename, e)
        return None


async def _create_context(playwright: Playwright, cfg: Dict[str, Any]) -> BrowserContext:
    state_path = BASE_DIR / cfg["session"]["storage_path"] / cfg["session"]["state_file"]
    geo = cfg["browser"].get("geolocation", {})

    context = await playwright.chromium.launch_persistent_context(
        user_data_dir=str(BASE_DIR / cfg["session"]["storage_path"] / "profile"),
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

    if state_path.exists():
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                storage_state = json.load(f)
            await context.add_cookies(storage_state.get("cookies", []))
            _logger.info("Session state loaded from %s", state_path)
        except Exception as e:
            _logger.warning("Failed to load session state: %s", e)
    else:
        _logger.info("No existing session state found, starting fresh")

    return context


async def _save_session_state(context: BrowserContext, cfg: Dict[str, Any]) -> None:
    state_path = BASE_DIR / cfg["session"]["storage_path"] / cfg["session"]["state_file"]
    try:
        cookies = await context.cookies()
        state = {"cookies": cookies, "origins": []}
        state_path.parent.mkdir(parents=True, exist_ok=True)
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        _logger.info("Session state saved to %s", state_path)
    except Exception as e:
        _logger.error("Failed to save session state: %s", e)


async def _manual_login(context: BrowserContext, cfg: Dict[str, Any]) -> bool:
    page = await context.new_page()
    try:
        await page.goto("https://www.google.com", timeout=cfg["browser"]["timeout"])
        _logger.info("Browser opened for manual login. You have 120 seconds to log in.")
        print("\n[MANUAL LOGIN] Browser is open. Complete your login steps.")
        print("[MANUAL LOGIN] Waiting up to 120 seconds for you to finish...")

        for remaining in range(120, 0, -1):
            print(f"\r[MANUAL LOGIN] Time remaining: {remaining}s. Press Ctrl+C when done.", end="")
            await asyncio.sleep(1)

        print("\n[MANUAL LOGIN] Time expired. Proceeding with current session state.")
        current_url = page.url
        _logger.info("Manual login completed. Current URL: %s", current_url)

        if cfg["session"]["auto_save"]:
            await _save_session_state(context, cfg)

        return True
    except asyncio.CancelledError:
        _logger.info("Manual login interrupted by user")
        if cfg["session"]["auto_save"]:
            await _save_session_state(context, cfg)
        return True
    except Exception as e:
        _logger.error("Error during manual login: %s", e)
        return False
    finally:
        await page.close()


async def setup_browser_session(cfg: Dict[str, Any]) -> bool:
    global _playwright_instance, _browser_context, _logger

    _logger.info("Starting browser session setup...")

    try:
        _playwright_instance = await async_playwright().start()
        _browser_context = await _create_context(_playwright_instance, cfg)
        _logger.info("Browser context created successfully")
        return True
    except Exception as e:
        _logger.error("Failed to create browser context: %s", e)
        return False


async def shutdown() -> None:
    global _playwright_instance, _browser_context, _logger

    _logger.info("Initiating graceful shutdown...")

    if _browser_context:
        try:
            cfg = _load_config()
            if cfg["session"]["auto_save"]:
                await _save_session_state(_browser_context, cfg)
            await _browser_context.close()
            _logger.info("Browser context closed")
        except Exception as e:
            _logger.warning("Error closing browser context: %s", e)
        finally:
            _browser_context = None

    if _playwright_instance:
        try:
            await _playwright_instance.stop()
            _logger.info("Playwright stopped")
        except Exception as e:
            _logger.warning("Error stopping Playwright: %s", e)
        finally:
            _playwright_instance = None

    _logger.info("Shutdown complete")


async def _menu_setup_browser_session(cfg: Dict[str, Any]) -> None:
    success = await setup_browser_session(cfg)
    if not success:
        print("\n[FAILED] Could not create browser session.")
        _logger.error("Browser session creation failed")
        return

    print("\n[SUCCESS] Browser session is active.")
    _logger.info("Browser session is active")

    choice = input("\nStart manual login? (y/n): ").strip().lower()
    if choice == "y":
        if _browser_context:
            await _manual_login(_browser_context, cfg)

    input("\nPress Enter to return to menu...")


async def _menu_run_clutch(cfg: Dict[str, Any]) -> None:
    if not _browser_context:
        print("\n[ERROR] No active browser session. Please run option 1 first.")
        _logger.warning("Clutch scraper requested but no browser session active")
        input("\nPress Enter to return to menu...")
        return

    print("\n" + "=" * 55)
    print("   CLUTCH.CO SCRAPER")
    print("=" * 55)
    print("   Using existing browser session.")
    _logger.info("Launching Clutch.co scraper")

    success = await run_clutch_scraper(_browser_context, _logger, cfg)

    if success:
        _logger.info("Clutch scraper completed successfully")
        print("\n[INFO] Clutch scraper finished.")
    else:
        _logger.warning("Clutch scraper completed with issues")
        print("\n[WARNING] Clutch scraper finished with issues.")

    input("\nPress Enter to return to menu...")


async def _menu_run_goodfirms(cfg: Dict[str, Any]) -> None:
    if not _browser_context:
        print("\n[ERROR] No active browser session. Please run option 1 first.")
        _logger.warning("GoodFirms scraper requested but no browser session active")
        input("\nPress Enter to return to menu...")
        return

    print("\n" + "=" * 55)
    print("   GOODFIRMS.CO SCRAPER")
    print("=" * 55)
    print("   Using existing browser session.")
    _logger.info("Launching GoodFirms.co scraper")

    success = await run_goodfirms_scraper(_browser_context, _logger, cfg)

    if success:
        _logger.info("GoodFirms scraper completed successfully")
        print("\n[INFO] GoodFirms scraper finished.")
    else:
        _logger.warning("GoodFirms scraper completed with issues")
        print("\n[WARNING] GoodFirms scraper finished with issues.")

    input("\nPress Enter to return to menu...")


async def _menu_run_maps(cfg: Dict[str, Any]) -> None:
    if not _browser_context:
        print("\n[ERROR] No active browser session. Please run option 1 first.")
        _logger.warning("Maps scraper requested but no browser session active")
        input("\nPress Enter to return to menu...")
        return

    print("\n" + "=" * 55)
    print("   GOOGLE MAPS SCRAPER")
    print("=" * 55)
    print("   Using existing browser session.")
    _logger.info("Launching Google Maps scraper")

    success = await run_maps_scraper(_browser_context, _logger, cfg)

    if success:
        _logger.info("Maps scraper completed successfully")
        print("\n[INFO] Maps scraper finished.")
    else:
        _logger.warning("Maps scraper completed with issues")
        print("\n[WARNING] Maps scraper finished with issues.")

    input("\nPress Enter to return to menu...")


async def _menu_run_linkedin(cfg: Dict[str, Any]) -> None:
    if not _browser_context:
        print("\n[ERROR] No active browser session. Please run option 1 first.")
        _logger.warning("LinkedIn enrichment requested but no browser session active")
        input("\nPress Enter to return to menu...")
        return

    print("\n" + "=" * 55)
    print("   LINKEDIN COMPANY ENRICHMENT")
    print("=" * 55)
    print("   Using existing browser session.")
    _logger.info("Launching LinkedIn enrichment")

    success = await run_linkedin_enrichment(_browser_context, _logger, cfg)

    if success:
        _logger.info("LinkedIn enrichment completed successfully")
        print("\n[INFO] LinkedIn enrichment finished.")
    else:
        _logger.warning("LinkedIn enrichment completed with issues")
        print("\n[WARNING] LinkedIn enrichment finished with issues.")

    input("\nPress Enter to return to menu...")


async def _menu_run_merge(cfg: Dict[str, Any]) -> None:
    print("\n" + "=" * 55)
    print("   MASTER MERGE ENGINE")
    print("=" * 55)
    print("   Merges all exported CSVs into one master lead sheet.")
    _logger.info("Launching merge engine")

    success = await run_merge_engine(_logger)

    if success:
        _logger.info("Merge completed successfully")
        print("\n[INFO] Merge finished.")
    else:
        _logger.warning("Merge completed with issues")
        print("\n[WARNING] Merge finished with issues.")

    input("\nPress Enter to return to menu...")


async def _show_menu(cfg: Dict[str, Any]) -> None:
    while True:
        print("\n" + "=" * 55)
        print("   LEAD EXTRACTION SYSTEM — MAIN MENU")
        print("=" * 55)
        print(f"   Browser Session: {'ACTIVE' if _browser_context else 'INACTIVE'}")
        print("-" * 55)
        print("   1. Setup Browser Session")
        print("   2. Run Clutch Scraper")
        print("   3. Run GoodFirms Scraper")
        print("   4. Run Google Maps Scraper")
        print("   5. Run LinkedIn Enrichment")
        print("   6. Merge All Leads")
        print("   7. Exit")
        print("=" * 55)

        choice = input("\nEnter your choice (1-7): ").strip()

        if choice == "1":
            await _menu_setup_browser_session(cfg)
        elif choice == "2":
            await _menu_run_clutch(cfg)
        elif choice == "3":
            await _menu_run_goodfirms(cfg)
        elif choice == "4":
            await _menu_run_maps(cfg)
        elif choice == "5":
            await _menu_run_linkedin(cfg)
        elif choice == "6":
            await _menu_run_merge(cfg)
        elif choice == "7":
            print("\nExiting...")
            break
        else:
            print("\n[ERROR] Invalid choice. Please enter 1, 2, 3, 4, 5, 6, or 7.")


async def main() -> None:
    global _logger

    _ensure_directories()
    _logger = _setup_logging()

    _logger.info("=" * 55)
    _logger.info("Lead Extraction System started")
    _logger.info("=" * 55)

    try:
        cfg = _load_config()
        _logger.info("Configuration loaded from %s", CONFIG_PATH)
    except Exception as e:
        _logger.critical("Failed to load config: %s", e)
        sys.exit(1)

    print(f"\nLead Extraction System v1.0")
    print(f"Working directory: {BASE_DIR}")

    try:
        await _show_menu(cfg)
    except KeyboardInterrupt:
        _logger.info("Interrupted by user")
    finally:
        await shutdown()
        logging.shutdown()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main())
