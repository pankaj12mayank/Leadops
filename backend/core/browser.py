import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Optional

from playwright.async_api import BrowserContext, Playwright, async_playwright

from backend.auth.session import decrypt_state, encrypt_state, make_key_from_secret
from backend.config.loader import BASE_DIR, get_session_encrypt_key

_playwright: Optional[Playwright] = None
_context: Optional[BrowserContext] = None
_logger: Optional[logging.Logger] = None


def _log() -> logging.Logger:
    global _logger
    if _logger is None:
        _logger = logging.getLogger("lead_system.browser")
    return _logger


async def init_browser(cfg: dict[str, Any]) -> bool:
    global _playwright, _context
    if _context is not None:
        _log().info("Browser already initialized")
        return True

    try:
        _log().info("Starting Playwright (visible mode)")
        _playwright = await async_playwright().start()
        geo = cfg["browser"].get("geolocation", {})

        _context = await _playwright.chromium.launch_persistent_context(
            user_data_dir=str(BASE_DIR / cfg["session"]["storage_path"] / "profile"),
            headless=False,
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
                enc_key_secret = get_session_encrypt_key()
                storage_state = None
                if enc_key_secret:
                    key = make_key_from_secret(enc_key_secret)
                    if key:
                        storage_state = decrypt_state(raw, key)
                if storage_state is None:
                    storage_state = json.loads(raw)
                await _context.add_cookies(storage_state.get("cookies", []))
                _log().info("Session state loaded from %s", state_path)
            except (json.JSONDecodeError, KeyError, OSError) as e:
                _log().warning("Failed to load session state: %s", e)
        else:
            _log().info("No existing session state, starting fresh")

        _log().info("Browser initialized (visible mode, persistent profile)")
        return True
    except Exception as e:
        _log().error("Failed to initialize browser: %s", e)
        _playwright = None
        _context = None
        return False


async def get_context() -> BrowserContext:
    if _context is None:
        raise RuntimeError("Browser not initialized. Call init_browser() first.")
    return _context


async def save_session(cfg: dict[str, Any]) -> None:
    if _context is None:
        return
    state_path = BASE_DIR / cfg["session"]["storage_path"] / cfg["session"]["state_file"]
    try:
        cookies = await _context.cookies()
        state = {"cookies": cookies, "origins": []}
        state_path.parent.mkdir(parents=True, exist_ok=True)

        enc_key_secret = get_session_encrypt_key()
        if enc_key_secret:
            key = make_key_from_secret(enc_key_secret)
            if key:
                encrypted = encrypt_state(state, key)
                state_path.write_text(encrypted, encoding="utf-8")
                _log().info("Session state encrypted and saved to %s", state_path)
                return

        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        _log().info("Session state saved to %s", state_path)
    except Exception as e:
        _log().error("Failed to save session state: %s", e)


async def close_browser() -> None:
    global _playwright, _context
    _log().info("Closing browser")

    if _context:
        try:
            await _context.close()
            _log().info("Browser context closed")
        except Exception as e:
            _log().warning("Error closing context: %s", e)
        _context = None

    if _playwright:
        try:
            await _playwright.stop()
            _log().info("Playwright stopped")
        except Exception as e:
            _log().warning("Error stopping Playwright: %s", e)
        _playwright = None


async def check_health() -> bool:
    if _context is None:
        return False
    try:
        pages = _context.pages
        _ = len(pages)
        return True
    except Exception:
        return False
