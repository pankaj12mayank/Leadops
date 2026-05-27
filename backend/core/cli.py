import asyncio
import json
import logging
import random
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from playwright.async_api import (
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

from backend.auth.session import decrypt_state, encrypt_state, make_key_from_secret
from backend.config.loader import (
    BASE_DIR,
    CONFIG_PATH,
    ensure_directories,
    get_session_encrypt_key,
    load_config,
    setup_logging,
)
from backend.scrapers.agency import clutch, goodfirms
from backend.scrapers.base import run_linkedin_enrichment, run_maps_scraper, run_search_scraper
from backend.storage.database import create_job, import_csv_to_db, init_db, update_job
from backend.storage.merge import cleanup_old_exports, run_merge_engine

_playwright_instance: Playwright | None = None
_browser_context: BrowserContext | None = None
_logger: logging.Logger | None = None


def _validate_query(query: str) -> str | None:
    if not query:
        return "Search query cannot be empty"
    if len(query) > 200:
        return "Search query must be 200 characters or fewer"
    if any(ord(c) < 32 for c in query):
        return "Search query contains invalid control characters"
    return None


def _validate_page_count(value: str, label: str, minimum: int = 1, maximum: int = 20) -> str | None:
    if not value:
        return None
    try:
        n = int(value)
    except ValueError:
        return f"{label} must be a valid number"
    if n < minimum:
        return f"{label} cannot be less than {minimum}"
    if n > maximum:
        return f"{label} cannot exceed {maximum}"
    return None


async def _random_delay(min_sec: float, max_sec: float) -> None:
    await asyncio.sleep(random.uniform(min_sec, max_sec))


async def _save_screenshot(page: Page, label: str = "screenshot") -> Path | None:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_label = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in label)
    path = BASE_DIR / "storage" / "screenshots" / f"{ts}_{safe_label}.png"
    try:
        await page.screenshot(path=str(path), full_page=True)
        _logger.info("Screenshot saved: %s", path)
        return path
    except Exception as e:
        _logger.error("Failed to save screenshot: %s", e)
        return None


_logger = logging.getLogger("lead_system")


async def _create_context(playwright: Playwright, cfg: dict[str, Any]) -> BrowserContext:
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
        bypass_csp=cfg["browser"].get("bypass_csp", False),
        ignore_https_errors=cfg["browser"].get("ignore_https_errors", False),
        no_viewport=False,
    )

    if state_path.exists():
        try:
            raw = state_path.read_text(encoding="utf-8")
            enc_key_secret = get_session_encrypt_key()
            storage_state = None
            if enc_key_secret:
                key = make_key_from_secret(enc_key_secret)
                if key:
                    storage_state = decrypt_state(raw, key)
            if storage_state is None:
                storage_state = json.loads(raw)
            await context.add_cookies(storage_state.get("cookies", []))
            _logger.info("Session state loaded from %s", state_path)
        except Exception as e:
            _logger.warning("Failed to load session state: %s", e)
    else:
        _logger.info("No existing session state found, starting fresh")

    return context


async def _save_session_state(context: BrowserContext, cfg: dict[str, Any]) -> None:
    state_path = BASE_DIR / cfg["session"]["storage_path"] / cfg["session"]["state_file"]
    try:
        cookies = await context.cookies()
        state = {"cookies": cookies, "origins": []}
        state_path.parent.mkdir(parents=True, exist_ok=True)

        enc_key_secret = get_session_encrypt_key()
        if enc_key_secret:
            key = make_key_from_secret(enc_key_secret)
            if key:
                encrypted = encrypt_state(state, key)
                state_path.write_text(encrypted, encoding="utf-8")
                _logger.info("Session state encrypted and saved to %s", state_path)
                return

        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        _logger.info("Session state saved to %s (unencrypted)", state_path)
    except Exception as e:
        _logger.error("Failed to save session state: %s", e)


async def _manual_login(context: BrowserContext, cfg: dict[str, Any]) -> bool:
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


async def setup_browser_session(cfg: dict[str, Any]) -> bool:
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
            cfg = load_config()
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


async def _menu_setup_browser_session(cfg: dict[str, Any]) -> None:
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


async def _run_scraper_with_db(
    source: str,
    query: str | None,
    coro,
) -> bool:
    job_id = create_job(source=source, query=query, status="running")
    try:
        result = await coro
        if result:
            total = import_csv_to_db(source, job_id, _logger)
            update_job(job_id, status="completed", total_found=total, preview_generated=1)
        else:
            update_job(job_id, status="failed", error_message="Scraper returned False")
        return result
    except asyncio.CancelledError:
        update_job(job_id, status="cancelled")
        raise
    except Exception as e:
        update_job(job_id, status="failed", error_message=str(e))
        raise


async def _menu_run_clutch(cfg: dict[str, Any]) -> None:
    if not _browser_context:
        print("\n[ERROR] No active browser session. Please run option 1 first.")
        _logger.warning("Clutch scraper requested but no browser session active")
        input("\nPress Enter to return to menu...")
        return

    print("\n" + "=" * 55)
    print("   CLUTCH.CO SCRAPER")
    print("=" * 55)
    print("   Using existing browser session.")
    query = input("Enter search query (e.g., 'marketing agencies USA'): ").strip()
    qe = _validate_query(query)
    if qe:
        print(f"[ERROR] {qe}.")
        input("\nPress Enter to return to menu...")
        return
    max_pages_str = input("Max pages to scrape (default 5): ").strip()
    pe = _validate_page_count(max_pages_str, "Max pages")
    if pe:
        print(f"[ERROR] {pe}. Using default of 5.")
        max_pages = 5
    else:
        max_pages = int(max_pages_str) if max_pages_str else 5
    _logger.info("Launching Clutch.co scraper")

    async def _run():
        return await run_search_scraper(
            _browser_context, _logger, cfg, query, max_pages,
            clutch.SELECTORS, clutch.build_search_url, clutch.extract_all_cards,
            "clutch", "agency",
        )

    success = await _run_scraper_with_db("clutch", query, _run())

    if success:
        _logger.info("Clutch scraper completed successfully")
        print("\n[INFO] Clutch scraper finished.")
    else:
        _logger.warning("Clutch scraper completed with issues")
        print("\n[WARNING] Clutch scraper finished with issues.")

    input("\nPress Enter to return to menu...")


async def _menu_run_goodfirms(cfg: dict[str, Any]) -> None:
    if not _browser_context:
        print("\n[ERROR] No active browser session. Please run option 1 first.")
        _logger.warning("GoodFirms scraper requested but no browser session active")
        input("\nPress Enter to return to menu...")
        return

    print("\n" + "=" * 55)
    print("   GOODFIRMS.CO SCRAPER")
    print("=" * 55)
    print("   Using existing browser session.")
    query = input("Enter search query (e.g., 'software companies USA'): ").strip()
    qe = _validate_query(query)
    if qe:
        print(f"[ERROR] {qe}.")
        input("\nPress Enter to return to menu...")
        return
    max_pages_str = input("Max pages to scrape (default 5): ").strip()
    pe = _validate_page_count(max_pages_str, "Max pages")
    if pe:
        print(f"[ERROR] {pe}. Using default of 5.")
        max_pages = 5
    else:
        max_pages = int(max_pages_str) if max_pages_str else 5
    _logger.info("Launching GoodFirms.co scraper")

    async def _run():
        return await run_search_scraper(
            _browser_context, _logger, cfg, query, max_pages,
            goodfirms.SELECTORS, goodfirms.build_search_url, goodfirms.extract_all_cards,
            "goodfirms", "agency",
        )

    success = await _run_scraper_with_db("goodfirms", query, _run())

    if success:
        _logger.info("GoodFirms scraper completed successfully")
        print("\n[INFO] GoodFirms scraper finished.")
    else:
        _logger.warning("GoodFirms scraper completed with issues")
        print("\n[WARNING] GoodFirms scraper finished with issues.")

    input("\nPress Enter to return to menu...")


async def _menu_run_maps(cfg: dict[str, Any]) -> None:
    if not _browser_context:
        print("\n[ERROR] No active browser session. Please run option 1 first.")
        _logger.warning("Maps scraper requested but no browser session active")
        input("\nPress Enter to return to menu...")
        return

    print("\n" + "=" * 55)
    print("   GOOGLE MAPS SCRAPER")
    print("=" * 55)
    print("   Using existing browser session.")
    query = input("Enter search query (e.g., 'marketing agencies in Dubai'): ").strip()
    qe = _validate_query(query)
    if qe:
        print(f"[ERROR] {qe}.")
        input("\nPress Enter to return to menu...")
        return
    scroll_cycles_str = input("Max scroll cycles (default 30): ").strip()
    ce = _validate_page_count(scroll_cycles_str, "Max scroll cycles", maximum=1000)
    if ce:
        print(f"[ERROR] {ce}. Using default of 30.")
        max_cycles = 30
    else:
        max_cycles = int(scroll_cycles_str) if scroll_cycles_str else 30
    _logger.info("Launching Google Maps scraper")

    async def _run():
        return await run_maps_scraper(_browser_context, _logger, cfg, query, max_cycles)

    success = await _run_scraper_with_db("maps", query, _run())

    if success:
        _logger.info("Maps scraper completed successfully")
        print("\n[INFO] Maps scraper finished.")
    else:
        _logger.warning("Maps scraper completed with issues")
        print("\n[WARNING] Maps scraper finished with issues.")

    input("\nPress Enter to return to menu...")


async def _menu_run_linkedin(cfg: dict[str, Any]) -> None:
    if not _browser_context:
        print("\n[ERROR] No active browser session. Please run option 1 first.")
        _logger.warning("LinkedIn enrichment requested but no browser session active")
        input("\nPress Enter to return to menu...")
        return

    print("\n" + "=" * 55)
    print("   LINKEDIN COMPANY ENRICHMENT")
    print("=" * 55)
    print("   Lightweight enrichment — safe, slow, logged-in session only.")
    print("   Using existing browser session.")
    export_dir = cfg.get("paths", {}).get("exports", "content")
    default_csv = BASE_DIR / export_dir / "startup" / "input_companies.csv"
    input_csv = input(f"Path to CSV with companies (default: {default_csv}): ").strip()
    csv_path = Path(input_csv) if input_csv else default_csv
    if not csv_path.exists():
        print(f"\n[ERROR] File not found: {csv_path}")
        print("[INFO] Create a CSV with columns: company_name, website (website optional)")
        input("\nPress Enter to return to menu...")
        return
    confirm = input("\nProceed with enrichment? (y/n): ").strip().lower()
    if confirm != "y":
        print("Cancelled.")
        input("\nPress Enter to return to menu...")
        return
    _logger.info("Launching LinkedIn enrichment")

    async def _run():
        return await run_linkedin_enrichment(_browser_context, _logger, cfg, csv_path)

    success = await _run_scraper_with_db("linkedin", str(csv_path), _run())

    if success:
        _logger.info("LinkedIn enrichment completed successfully")
        print("\n[INFO] LinkedIn enrichment finished.")
    else:
        _logger.warning("LinkedIn enrichment completed with issues")
        print("\n[WARNING] LinkedIn enrichment finished with issues.")

    input("\nPress Enter to return to menu...")


async def _menu_run_merge(cfg: dict[str, Any]) -> None:
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


async def _show_menu(cfg: dict[str, Any]) -> None:
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
        print("   7. Cleanup Old Exports")
        print("   8. Exit")
        print("=" * 55)

        choice = input("\nEnter your choice (1-8): ").strip()

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
            loop = asyncio.get_running_loop()
            deleted = await loop.run_in_executor(None, cleanup_old_exports, _logger)
            print(f"\nCleanup removed {deleted} old export file(s).")
        elif choice == "8":
            print("\nExiting...")
            break
        else:
            print("\n[ERROR] Invalid choice. Please enter 1-8.")


async def main() -> None:
    global _logger

    if sys.version_info < (3, 10):
        print("ERROR: Python 3.10+ required")
        sys.exit(1)

    in_venv = sys.prefix != sys.base_prefix
    if not in_venv:
        print("WARNING: Not running in a virtual environment. Create one with: python -m venv venv")

    ensure_directories()
    init_db()
    _logger = setup_logging("lead_system")

    _logger.info("=" * 55)
    _logger.info("Lead Extraction System started")
    _logger.info("=" * 55)

    cfg = load_config()
    _logger.info("Configuration loaded from %s", CONFIG_PATH)

    print("\nLead Extraction System v1.0")
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
