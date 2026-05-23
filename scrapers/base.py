import asyncio
import logging
import random
import re
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from playwright.async_api import Page

BASE_DIR = Path(__file__).resolve().parent.parent


class ScraperError(Exception):
    pass


class NavigationError(ScraperError):
    pass


class ExtractionError(ScraperError):
    pass


class ExportError(ScraperError):
    pass


class CaptchaDetectedError(ScraperError):
    pass


class RateLimitError(ScraperError):
    pass


_CIRCUIT_HISTORY: dict[str, deque] = defaultdict(lambda: deque(maxlen=20))


def _circuit_open(label: str) -> bool:
    history = _CIRCUIT_HISTORY[label]
    if len(history) < 10:
        return False
    failures = sum(1 for r in history if r == "fail")
    return failures / len(history) > 0.5


def _circuit_record(label: str, result: str) -> None:
    _CIRCUIT_HISTORY[label].append(result)


async def scroll_slowly(page: Page, logger: logging.Logger, steps: int = 8, delay: float = 0.4) -> None:
    try:
        total_height = await page.evaluate("document.body.scrollHeight")
        step_size = max(1, total_height // steps)
        for i in range(1, steps + 1):
            scroll_to = min(i * step_size, total_height)
            await page.evaluate(f"window.scrollTo(0, {scroll_to})")
            await asyncio.sleep(delay * (0.8 + random.random() * 0.4))
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(0.5)
        await page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(0.3)
    except Exception as e:
        logger.warning("Scroll interrupted: %s", e)


async def accept_cookies(page: Page, logger: logging.Logger, selectors: str, timeout: int = 5000) -> bool:
    try:
        for sel in selectors.split(", "):
            btn = page.locator(sel).first
            if await btn.count() > 0:
                await btn.click(timeout=timeout)
                await asyncio.sleep(0.5)
                return True
    except Exception:
        pass
    return False


async def safe_extract_text(
    page: Page, parent, selector: str, logger: logging.Logger, timeout: int = 2000
) -> str | None:
    for single_sel in selector.split(", "):
        try:
            el = parent.locator(single_sel).first
            if await el.count() > 0 and await el.is_visible(timeout=timeout):
                text = (await el.inner_text()).strip()
                if text:
                    return text
        except Exception:
            continue
    return None


async def safe_extract_href(
    page: Page, parent, selector: str, logger: logging.Logger, timeout: int = 2000
) -> str | None:
    for single_sel in selector.split(", "):
        try:
            el = parent.locator(single_sel).first
            if await el.count() > 0 and await el.is_visible(timeout=timeout):
                href = await el.get_attribute("href")
                if href and href.strip():
                    return href.strip()
        except Exception:
            continue
    return None


async def safe_extract_attribute(
    page: Page, parent, selector: str, attr: str, logger: logging.Logger, timeout: int = 2000
) -> str | None:
    for single_sel in selector.split(", "):
        try:
            el = parent.locator(single_sel).first
            if await el.count() > 0:
                val = await el.get_attribute(attr)
                if val:
                    return val.strip()
        except Exception:
            continue
    return None


async def extract_rating_from_text(text: str | None) -> float | None:
    if not text:
        return None
    for pattern in [r"([\d.]+)\s*/\s*5", r"([\d.]+)\s*out\s*of\s*5", r"^([\d.]+)$"]:
        match = re.search(pattern, text.strip(), re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                pass
    match = re.search(r"rating[:\s]*([\d.]+)", text, re.IGNORECASE)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return None


async def extract_employees(text: str | None) -> str | None:
    if not text:
        return None
    text = text.strip()
    patterns = [
        (r"(\d[\d,]*\s*-\s*\d[\d,]*)\s*(Employees?|people|team)", lambda m: m.group(1).replace(",", "").strip()),
        (r"(\d[\d,]*\+?\s*Employees?)", lambda m: m.group(1).strip()),
        (r"(\d[\d,]*)\s*-\s*(\d[\d,]*)\s*(emp|employees)", lambda m: f"{m.group(1)}-{m.group(2)}"),
        (r"(\d[\d,]*)\s*-\s*(\d[\d,]*)", lambda m: f"{m.group(1)}-{m.group(2)}"),
    ]
    for pat, fmt in patterns:
        match = re.search(pat, text, re.IGNORECASE)
        if match:
            return fmt(match)
    if re.match(r"^\d[\d,]*\+?$", text):
        return text
    return text if any(c.isdigit() for c in text) else None


async def extract_hourly_rate(text: str | None) -> str | None:
    if not text:
        return None
    text = text.strip()
    patterns = [
        (r"\$(\d[\d]*)\s*-\s*\$(\d[\d]*)\s*/hr", lambda m: f"${m.group(1)}-${m.group(2)}/hr"),
        (r"(\$[\d]+)\s*/\s*hr", lambda m: m.group(1) + "/hr"),
        (r"\$(\d[\d]*)\s*-\s*\$(\d[\d]*)", lambda m: f"${m.group(1)}-${m.group(2)}"),
        (r"(\$[\d]+)", lambda m: m.group(1)),
    ]
    for pat, fmt in patterns:
        match = re.search(pat, text, re.IGNORECASE)
        if match:
            return fmt(match)
    if text.startswith("$") or "/hr" in text:
        return text
    return None


async def extract_services(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = re.sub(r"\s+", " ", text).strip()
    cleaned = re.sub(r"\s*,\s*", ", ", cleaned)
    return cleaned if len(cleaned) > 1 else None


async def navigate_with_retry(page: Page, url: str, logger: logging.Logger, cfg: dict[str, Any]) -> bool:
    timeout = cfg["browser"]["timeout"]
    retry_count = cfg["browser"]["retry_count"]
    for attempt in range(1, retry_count + 1):
        try:
            ok = await page.goto(url, timeout=timeout, wait_until="domcontentloaded")
            if ok is None:
                raise NavigationError("Navigation returned None")
            try:
                await page.wait_for_load_state("networkidle", timeout=timeout)
            except Exception:
                logger.debug("networkidle timed out, continuing")
            return True
        except Exception as e:
            logger.warning("Navigation attempt %d/%d failed for %s: %s", attempt, retry_count, url, e)
            if attempt < retry_count:
                delay = min(60.0, (2 ** attempt) + random.uniform(0, 1))
                await asyncio.sleep(delay)
    logger.error("All %d navigation attempts failed for %s", retry_count, url)
    return False


async def has_results(page: Page, logger: logging.Logger, no_result_selectors: str, card_selectors: str) -> bool:
    try:
        for sel in no_result_selectors.split(", "):
            el = page.locator(sel).first
            if await el.count() > 0 and await el.is_visible(timeout=1000):
                logger.info("No results message detected via: %s", sel)
                return False
    except Exception:
        pass
    try:
        first_sel = card_selectors.split(", ")[0]
        cards = page.locator(first_sel)
        if await cards.count() > 0:
            return True
    except Exception:
        pass
    try:
        body_text = await page.locator("body").inner_text(timeout=3000)
        body_lower = body_text.lower()
        no_result_phrases = ["no results", "no companies", "nothing found"]
        if any(phrase in body_lower for phrase in no_result_phrases):
            return False
    except Exception:
        pass
    return True


def build_page_url(base_url: str, page_num: int) -> str:
    if page_num <= 1:
        return base_url
    sep = "&" if "?" in base_url else "?"
    return f"{base_url}{sep}page={page_num}"


async def go_to_next_page(
    page: Page, logger: logging.Logger, cfg: dict[str, Any],
    current_page: int, next_button_selectors: str,
) -> int | None:
    timeout = cfg["browser"]["timeout"]
    min_delay = cfg["browser"]["min_delay"]
    max_delay = cfg["browser"]["max_delay"]

    try:
        await scroll_slowly(page, logger, steps=4, delay=0.3)
    except Exception:
        pass

    btn = page.locator(next_button_selectors).first
    try:
        if await btn.count() == 0 or not await btn.is_visible(timeout=3000):
            return None
        is_disabled = await btn.get_attribute("disabled")
        if is_disabled:
            return None
        class_attr = await btn.get_attribute("class")
        if class_attr and "disabled" in class_attr.lower():
            return None
    except Exception:
        return None

    try:
        next_page = current_page + 1
        url = page.url
        if "page=" in url:
            new_url = re.sub(r"page=\d+", f"page={next_page}", url)
        else:
            sep = "&" if "?" in url else "?"
            new_url = f"{url}{sep}page={next_page}"
        logger.info("Navigating to page %d: %s", next_page, new_url)
        await page.goto(new_url, timeout=timeout, wait_until="domcontentloaded")
        await page.wait_for_load_state("networkidle", timeout=timeout)
        await asyncio.sleep(random.uniform(min_delay, max_delay))
        return next_page
    except Exception:
        try:
            logger.info("Trying click-based navigation")
            await btn.click(timeout=timeout)
            await page.wait_for_load_state("networkidle", timeout=timeout)
            await asyncio.sleep(random.uniform(min_delay, max_delay))
            return current_page + 1
        except Exception as e2:
            logger.error("Click navigation failed: %s", e2)
            return None


async def retry_extraction(coro, logger, max_retries: int = 2, delay: float = 1.0, label: str = "item"):
    if _circuit_open(label):
        logger.warning("Circuit open for '%s', skipping extraction", label)
        return None
    for attempt in range(1, max_retries + 1):
        try:
            result = await coro
            _circuit_record(label, "ok")
            return result
        except Exception as e:
            logger.warning("Retry %d/%d for %s failed: %s", attempt, max_retries, label, e)
            if attempt < max_retries:
                await asyncio.sleep(delay * attempt)
    _circuit_record(label, "fail")
    return None


def export_dataframe_to_file(
    df: pd.DataFrame,
    filename_prefix: str,
    subdir: str,
    cfg: dict[str, Any],
    logger: logging.Logger,
) -> Path | None:
    if df.empty:
        logger.warning("DataFrame is empty, skipping export for %s", filename_prefix)
        return None

    export_format = cfg["export"]["format"]
    safe_prefix = re.sub(r"[^\w\-_]", "_", filename_prefix.strip().lower())[:80]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{ts}_{safe_prefix}"
    ext = export_format.strip().lower()
    known = {"csv", "json", "parquet", "xlsx"}
    if ext not in known:
        logger.warning("Unknown export format '%s', falling back to csv", ext)
        ext = "csv"

    out = BASE_DIR / "exports" / subdir / f"{filename}.{ext}"
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
                logger.error("XLSX export failed: %s, falling back to CSV", xl_err)
                ext = "csv"
                out = out.with_suffix(".csv")
                df.to_csv(out, index=False, encoding="utf-8-sig")
        logger.info("Exported %d rows to %s", len(df), out)
        return out
    except Exception as e:
        logger.error("Export failed for %s: %s", filename_prefix, e)
        return None
