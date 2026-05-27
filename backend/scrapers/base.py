import asyncio
import logging
import random
import re
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from playwright.async_api import Page

from backend.config.loader import BASE_DIR
from backend.core.exporter import sanitize_dataframe
from backend.core.normalizer import normalize_leads


class ScraperError(Exception):
    pass


class NavigationError(ScraperError):
    pass


_CIRCUIT_HISTORY: dict[tuple[str, str], deque] = defaultdict(lambda: deque(maxlen=20))


def _circuit_open(label: str, namespace: str = "global") -> bool:
    key = (namespace, label)
    history = _CIRCUIT_HISTORY[key]
    if len(history) < 10:
        return False
    failures = sum(1 for r in history if r == "fail")
    return failures / len(history) > 0.5


def _circuit_record(label: str, result: str, namespace: str = "global") -> None:
    key = (namespace, label)
    _CIRCUIT_HISTORY[key].append(result)


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
        for sel in re.split(r",\s+", selectors.strip()):
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
            if not ok.ok:
                raise NavigationError(f"Navigation returned HTTP {ok.status}")
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


async def retry_extraction(coro, logger, max_retries: int = 2, delay: float = 1.0, label: str = "item", namespace: str = "global"):
    if _circuit_open(label, namespace):
        logger.warning("Circuit open for '%s', skipping extraction", label)
        return None
    for attempt in range(1, max_retries + 1):
        try:
            result = await coro
            _circuit_record(label, "ok", namespace)
            return result
        except Exception as e:
            logger.warning("Retry %d/%d for %s failed: %s", attempt, max_retries, label, e)
            if attempt < max_retries:
                await asyncio.sleep(delay * attempt)
    _circuit_record(label, "fail", namespace)
    return None


async def run_search_scraper(
    context,
    logger: logging.Logger,
    cfg: dict[str, Any],
    query: str,
    max_pages: int,
    selectors: dict[str, str],
    build_search_url,
    extract_all_cards,
    source_name: str,
    content_subdir: str,
    progress_callback: Callable[[int, int, int], Awaitable[None]] | None = None,
) -> bool:
    page: Page | None = None
    all_leads: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    current_page = 1

    try:
        page = await context.new_page()
        search_url = build_search_url(query, cfg)
        logger.info("Search URL: %s", search_url)

        if not await navigate_with_retry(page, search_url, logger, cfg):
            logger.error("All navigation attempts failed for %s", source_name)
            print(f"[ERROR] Could not load {source_name}. Check your connection.")
            return False

        await accept_cookies(page, logger, selectors.get("cookie_accept", ""))
        await asyncio.sleep(random.uniform(cfg["browser"]["min_delay"], cfg["browser"]["max_delay"]))

        if not await has_results(page, logger, selectors.get("no_results", ""), selectors.get("result_cards", "")):
            logger.info("No results found for query: %s", query)
            print(f"[INFO] No results found for '{query}'.")
            return True

        while current_page <= max_pages:
            logger.info("--- %s page %d ---", source_name.title(), current_page)
            print(f"\n[PAGE {current_page}] Scraping...")

            if current_page > 1:
                url = f"{search_url}&page={current_page}"
                if not await navigate_with_retry(page, url, logger, cfg):
                    logger.error("Failed to load page %d, stopping", current_page)
                    break
                await accept_cookies(page, logger, selectors.get("cookie_accept", ""))
                await asyncio.sleep(random.uniform(cfg["browser"]["min_delay"], cfg["browser"]["max_delay"]))

            try:
                await scroll_slowly(page, logger, steps=10, delay=0.35)
            except Exception as e:
                logger.warning("Scroll failed on page %d: %s", current_page, e)

            cards_data = await extract_all_cards(page, cfg, seen_urls)
            all_leads.extend(cards_data)
            logger.info("Page %d: extracted %d leads (total: %d)", current_page, len(cards_data), len(all_leads))
            print(f"         Extracted: {len(cards_data)} leads (total: {len(all_leads)})")
            if progress_callback:
                await progress_callback(current_page, max_pages, len(all_leads))

            if current_page >= max_pages:
                break

            next_page = await go_to_next_page(page, logger, cfg, current_page, selectors.get("next_button", ""))
            if next_page is None:
                logger.info("No more pages available")
                print("[INFO] No more pages available.")
                break
            current_page = next_page

        if all_leads:
            export_leads(all_leads, source_name, f"{source_name}_{query[:50]}", content_subdir, cfg, logger)
        else:
            logger.info("No leads extracted")
            print("\n[INFO] No leads were extracted.")

        return True

    except asyncio.CancelledError:
        logger.warning("%s scraper interrupted by user", source_name.title())
        if all_leads:
            export_leads(all_leads, source_name, f"{source_name}_{query[:50]}", content_subdir, cfg, logger)
            print(f"\n[PARTIAL] Exported {len(all_leads)} leads.")
        print("\n[INTERRUPTED] Scraping stopped by user.")
        return False
    except Exception as e:
        logger.error("Unexpected %s scraper error: %s", source_name, e)
        print(f"\n[ERROR] Unexpected error: {e}")
        if all_leads:
            export_leads(all_leads, source_name, f"{source_name}_{query[:50]}", content_subdir, cfg, logger)
            print(f"[PARTIAL] Exported {len(all_leads)} leads.")
        return False
    finally:
        if page:
            try:
                await page.close()
            except Exception:
                pass


async def run_maps_scraper(
    context,
    logger: logging.Logger,
    cfg: dict[str, Any],
    query: str,
    max_cycles: int,
    progress_callback: Callable[[int, int, int], Awaitable[None]] | None = None,
) -> bool:
    from backend.scrapers.local.maps import (
        SELECTORS as MAPS_SELECTORS,
    )
    from backend.scrapers.local.maps import (
        build_search_url,
        check_captcha,
        extract_all_items,
        scroll_feed,
    )

    page = None
    all_leads: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    _exported_ok = False
    timeout = cfg["browser"]["timeout"]
    min_delay = cfg["browser"]["min_delay"]
    max_delay = cfg["browser"]["max_delay"]
    retry_count = cfg["browser"]["retry_count"]

    logger.info("Starting Maps scrape | query='%s' | max_cycles=%d", query, max_cycles)

    try:
        page = await context.new_page()
        search_url = build_search_url(query, cfg)
        logger.info("Search URL: %s", search_url)

        for attempt in range(1, retry_count + 1):
            try:
                logger.info("Navigation attempt %d/%d", attempt, retry_count)
                ok = await page.goto(search_url, timeout=timeout, wait_until="domcontentloaded")
                if ok is None:
                    raise Exception("Navigation returned None")
                try:
                    await page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    logger.debug("networkidle timed out")
                break
            except Exception as e:
                logger.warning("Navigation attempt %d failed: %s", attempt, e)
                if attempt < retry_count:
                    await asyncio.sleep(attempt * 3)
                else:
                    logger.error("All navigation attempts failed")
                    print("[ERROR] Could not load Google Maps. Check your connection.")
                    return False

        await asyncio.sleep(random.uniform(min_delay * 0.5, min_delay))

        if await check_captcha(page):
            logger.error("Captcha or rate-limit detected")
            print("\n[ERROR] Google is showing a captcha or rate-limit page.")
            return False

        feed_container = None
        try:
            feed = page.locator(MAPS_SELECTORS.get("feed_container", "div[role='feed']"))
            if await feed.count() > 0:
                feed_container = feed.first
        except Exception:
            pass

        current_count = 0
        try:
            for sel in MAPS_SELECTORS.get("result_items", "div").split(", "):
                current_count = await page.locator(sel).count()
                if current_count > 0:
                    break
        except Exception:
            pass

        if current_count == 0:
            logger.info("No results found for query: %s", query)
            print(f"[INFO] No results found for '{query}'.")
            return True

        logger.info("Initial item count: %d", current_count)
        print("\n[INFO] Found initial results. Beginning extraction...")

        consecutive_empty = 0
        max_empty_scrolls = 5

        for cycle in range(1, max_cycles + 1):
            logger.info("--- Scroll cycle %d/%d ---", cycle, max_cycles)
            print(f"\n[CYCLE {cycle}/{max_cycles}] Extracting visible results...")

            try:
                cards_data = await extract_all_items(page, seen_names)
            except Exception as e:
                logger.warning("Extraction failed on cycle %d: %s", cycle, e)
                await asyncio.sleep(random.uniform(min_delay, max_delay))
                continue

            new_in_cycle = [d for d in cards_data if d["business_name"].lower().strip() not in seen_names]
            all_leads.extend(new_in_cycle)
            logger.info("Cycle %d: extracted %d leads (new: %d, total: %d)", cycle, len(cards_data), len(new_in_cycle), len(all_leads))
            print(f"         Extracted: {len(cards_data)} leads (total: {len(all_leads)})")
            if progress_callback:
                await progress_callback(cycle, max_cycles, len(all_leads))

            if await check_captcha(page):
                logger.warning("Captcha detected during scrolling")
                print("\n[WARNING] Captcha detected. Stopping.")
                break

            if len(new_in_cycle) == 0:
                consecutive_empty += 1
                if consecutive_empty >= max_empty_scrolls:
                    logger.info("No new items after %d consecutive scrolls, stopping", max_empty_scrolls)
                    print(f"\n[INFO] No new results after {max_empty_scrolls} scrolls. Ending.")
                    break
            else:
                consecutive_empty = 0

            logger.info("Scrolling for more results...")
            print("         Scrolling for more...")
            await scroll_feed(page, feed_container)
            await asyncio.sleep(random.uniform(min_delay * 0.3, min_delay * 0.7))

        if all_leads:
            export_leads(all_leads, "maps", f"maps_{query[:50]}", "local", cfg, logger)
        else:
            logger.info("No leads extracted")
            print("\n[INFO] No leads were extracted.")
        _exported_ok = True
        return True

    except asyncio.CancelledError:
        logger.warning("Maps scraper interrupted by user")
        print("\n[INTERRUPTED] Scraping stopped by user.")
        return False
    except Exception as e:
        logger.error("Unexpected Maps scraper error: %s", e)
        print(f"\n[ERROR] Unexpected error: {e}")
        return False
    finally:
        try:
            if not _exported_ok and all_leads:
                export_leads(all_leads, "maps", f"maps_{query[:50]}", "local", cfg, logger)
                print(f"\n[PARTIAL] Exported {len(all_leads)} leads.")
        except Exception:
            pass
        if page:
            try:
                await page.close()
            except Exception:
                pass


async def run_linkedin_enrichment(
    context,
    logger: logging.Logger,
    cfg: dict[str, Any],
    csv_path: Path | None = None,
    progress_callback: Callable[[int, int, int], Awaitable[None]] | None = None,
) -> bool:
    import pandas as pd

    from backend.scrapers.startup.linkedin import enrich_company

    page = None
    all_results: list[dict[str, Any]] = []
    if csv_path is None:
        csv_path = BASE_DIR / "content" / "startup" / "input_companies.csv"
    input_path = csv_path

    if not input_path.exists():
        print(f"\n[ERROR] File not found: {input_path}")
        logger.error("CSV file not found: %s", input_path)
        return False

    try:
        df = pd.read_csv(input_path)
        df.columns = [c.strip().lower() for c in df.columns]
    except Exception as e:
        logger.error("Failed to read CSV: %s", e)
        return False

    name_col = website_col = None
    for col in df.columns:
        if col in ("company_name", "name", "company", "business_name", "business"):
            name_col = col
        if col in ("website", "url", "domain", "site", "web"):
            website_col = col

    if name_col is None:
        logger.error("No company name column found in CSV")
        return False

    total = len(df)
    logger.info("Loaded %d companies from %s", total, input_path)

    try:
        page = await context.new_page()
        delay_between = max(cfg["browser"]["max_delay"] * 2, 8.0)
        enriched_count = skipped_count = 0

        for idx, row in df.iterrows():
            company_name = str(row[name_col]).strip()
            website = str(row[website_col]).strip() if website_col and pd.notna(row.get(website_col, "")) else ""
            if not company_name or company_name.lower() in ("nan", "none", ""):
                skipped_count += 1
                continue

            result = await enrich_company(page, company_name, website, cfg)
            all_results.append(result)

            if result["enrichment_status"] == "enriched":
                enriched_count += 1

            if progress_callback:
                await progress_callback(idx + 1, total, enriched_count)
            elif result["enrichment_status"] in ("login_required", "rate_limit", "challenge"):
                logger.warning("LinkedIn barrier at company %d: %s", idx, result["enrichment_status"])
                break

            if idx < total - 1:
                jitter = random.uniform(0.8, 1.2)
                await asyncio.sleep(delay_between * jitter)

        if all_results:
            export_leads(all_results, "linkedin", "linkedin_enrichment", "startup", cfg, logger, normalize=False)
        return True

    except asyncio.CancelledError:
        logger.warning("LinkedIn enrichment interrupted by user")
        if all_results:
            export_leads(all_results, "linkedin", "linkedin_enrichment", "startup", cfg, logger, normalize=False)
        return False
    except Exception as e:
        logger.error("Unexpected LinkedIn enrichment error: %s", e)
        if all_results:
            export_leads(all_results, "linkedin", "linkedin_enrichment", "startup", cfg, logger, normalize=False)
        return False
    finally:
        if page:
            try:
                await page.close()
            except Exception:
                pass


def export_leads(
    leads: list[dict[str, Any]],
    source: str,
    filename_prefix: str,
    subdir: str,
    cfg: dict[str, Any],
    logger: logging.Logger,
    normalize: bool = True,
) -> Path | None:
    if not leads:
        logger.warning("No leads to export for %s", filename_prefix)
        return None
    if normalize:
        leads = normalize_leads(source, leads)
    df = pd.DataFrame(leads)
    return export_dataframe_to_file(df, filename_prefix, subdir, cfg, logger)


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

    out = BASE_DIR / "content" / subdir / f"{filename}.{ext}"
    try:
        if ext == "csv":
            sanitize_dataframe(df).to_csv(out, index=False, encoding="utf-8-sig")
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
                sanitize_dataframe(df).to_csv(out, index=False, encoding="utf-8-sig")
        logger.info("Exported %d rows to %s", len(df), out)
        return out
    except Exception as e:
        logger.error("Export failed for %s: %s", filename_prefix, e)
        return None
