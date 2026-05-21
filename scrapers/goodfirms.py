import asyncio
import logging
import random
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import pandas as pd
from playwright.async_api import (
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeout,
)

BASE_DIR = Path(__file__).resolve().parent.parent

SELECTORS = {
    "cookie_accept": (
        "button:has-text('Accept'), button:has-text('Got it'), "
        "button:has-text('Allow All'), button:has-text('Agree'), "
        "button:has-text('I Accept'), button:has-text('OK')"
    ),
    "result_cards": (
        "div[class*='company-card'], div[class*='listing-item'], "
        "div[class*='provider-item'], article[class*='company'], "
        "div[class*='result-item'], li[class*='company'], "
        "div[class*='provider-card']"
    ),
    "card_name": (
        "a[class*='company-name'], a[class*='provider-name'], "
        "a[class*='title'], h3 a, h4 a, a[class*='name'], "
        "a[class*='listing-name']"
    ),
    "card_website": (
        "a[class*='website'], a[class*='visit'], "
        "a[href*='http']:not([href*='goodfirms.co']):not([href*='goodfirms'])"
    ),
    "card_profile": (
        "a[class*='company-name'], a[class*='provider-name'], "
        "a[class*='title'], a[class*='name'], a[class*='listing-name'], "
        "a[class*='profile-link']"
    ),
    "card_location": (
        "[class*='location'], [class*='address'], [class*='country'], "
        "[class*='city'], [class*='region'], span[class*='locality'], "
        "div[class*='location'] span, [class*='based']"
    ),
    "card_employees": (
        "[class*='employee'], [class*='team-size'], [class*='team'], "
        "[class*='size'], [class*='headcount'], "
        "span:has-text('Employees') ~ span, "
        "span:has-text('employees') ~ span"
    ),
    "card_hourly_rate": (
        "[class*='rate'], [class*='hourly'], [class*='pricing'], "
        "span:has-text('$'), [class*='price'], "
        "span:has-text('/hr')"
    ),
    "card_services": (
        "[class*='service'], [class*='category'], [class*='expertise'], "
        "[class*='focus'], [class*='offer'], [class*='skill'], "
        "[class*='tag']"
    ),
    "card_rating": (
        "[class*='rating'], span[class*='score'], [class*='stars'], "
        "[class*='review-rating'], [class*='star-rating'], "
        "meta[itemprop='ratingValue']"
    ),
    "next_button": (
        "a[rel='next'], button[aria-label='Next'], "
        "a:has-text('Next'), a:has-text('next'), "
        "a:has-text('Next Page'), button:has-text('Next'), "
        "li.pager-next a, li.next a"
    ),
    "no_results": (
        "div:has-text('No results'), p:has-text('no results'), "
        "div:has-text('no companies'), div:has-text('Nothing found'), "
        "div:has-text('No companies found')"
    ),
    "results_count": (
        "[class*='result-count'], [class*='search-count'], "
        "span[class*='count'], [class*='total-count']"
    ),
}


def _build_search_url(query: str) -> str:
    q = query.strip().lower().replace(" ", "+")
    return f"https://www.goodfirms.co/search?q={q}"


def _build_page_url(base_url: str, page_num: int) -> str:
    if page_num <= 1:
        return base_url
    sep = "&" if "?" in base_url else "?"
    return f"{base_url}{sep}page={page_num}"


async def _scroll_slowly(page: Page, logger, steps: int = 8, delay: float = 0.4) -> None:
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
        logger.debug("Slow scroll completed: %d steps", steps)
    except Exception as e:
        logger.warning("Slow scroll interrupted: %s", e)


async def _accept_cookies(page: Page, logger, timeout: int = 5000) -> bool:
    try:
        for sel in SELECTORS["cookie_accept"].split(", "):
            btn = page.locator(sel).first
            if await btn.count() > 0:
                await btn.click(timeout=timeout)
                logger.debug("Cookie consent accepted via: %s", sel)
                await asyncio.sleep(0.5)
                return True
    except Exception:
        pass
    return False


async def _safe_extract_text(page: Page, card, selector: str, logger, timeout: int = 2000) -> Optional[str]:
    for single_sel in selector.split(", "):
        try:
            el = card.locator(single_sel).first
            if await el.count() > 0 and await el.is_visible(timeout=timeout):
                text = (await el.inner_text()).strip()
                if text:
                    return text
        except Exception:
            continue
    return None


async def _safe_extract_href(page: Page, card, selector: str, logger, timeout: int = 2000) -> Optional[str]:
    for single_sel in selector.split(", "):
        try:
            el = card.locator(single_sel).first
            if await el.count() > 0 and await el.is_visible(timeout=timeout):
                href = await el.get_attribute("href")
                if href and href.strip():
                    href = href.strip()
                    if href.startswith("/"):
                        href = "https://www.goodfirms.co" + href
                    return href
        except Exception:
            continue
    return None


async def _extract_rating_from_text(text: str) -> Optional[float]:
    if not text:
        return None
    match = re.search(r"([\d.]+)\s*/\s*5", text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    match = re.search(r"([\d.]+)\s*out\s*of\s*5", text, re.IGNORECASE)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    match = re.search(r"^([\d.]+)$", text.strip())
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


async def _extract_employees(text: str) -> Optional[str]:
    if not text:
        return None
    text = text.strip()
    match = re.search(r"(\d[\d,]*\s*-\s*\d[\d,]*)\s*(Employees?|people|team)", text, re.IGNORECASE)
    if match:
        return match.group(1).replace(",", "").strip()
    match = re.search(r"(\d[\d,]*\+?\s*Employees?)", text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    match = re.search(r"(\d[\d,]*)\s*-\s*(\d[\d,]*)\s*(emp|employees)", text, re.IGNORECASE)
    if match:
        return f"{match.group(1)}-{match.group(2)}"
    match = re.search(r"(\d[\d,]*)\s*-\s*(\d[\d,]*)", text)
    if match:
        return f"{match.group(1)}-{match.group(2)}"
    if re.match(r"^\d[\d,]*\+?$", text):
        return text
    return text if any(c.isdigit() for c in text) else None


async def _extract_hourly_rate(text: str) -> Optional[str]:
    if not text:
        return None
    text = text.strip()
    match = re.search(r"\$(\d[\d]*)\s*-\s*\$(\d[\d]*)\s*/hr", text, re.IGNORECASE)
    if match:
        return f"${match.group(1)}-${match.group(2)}/hr"
    match = re.search(r"(\$[\d]+)\s*/\s*hr", text, re.IGNORECASE)
    if match:
        return match.group(1) + "/hr"
    match = re.search(r"\$(\d[\d]*)\s*-\s*\$(\d[\d]*)", text)
    if match:
        return f"${match.group(1)}-${match.group(2)}"
    match = re.search(r"(\$[\d]+)", text)
    if match:
        return match.group(1)
    if text.startswith("$") or "/hr" in text:
        return text
    return None


async def _extract_services(text: str) -> Optional[str]:
    if not text:
        return None
    cleaned = re.sub(r"\s+", " ", text).strip()
    cleaned = re.sub(r"\s*,\s*", ", ", cleaned)
    return cleaned if len(cleaned) > 1 else None


async def _extract_card_data(page: Page, card, logger, cfg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        if not await card.is_visible(timeout=2000):
            return None
    except Exception:
        return None

    try:
        name = await _safe_extract_text(page, card, SELECTORS["card_name"], logger)
        if not name:
            return None
        name = re.sub(r"\s+", " ", name).strip()
    except Exception:
        return None

    profile_url = await _safe_extract_href(page, card, SELECTORS["card_profile"], logger)
    website = await _safe_extract_href(page, card, SELECTORS["card_website"], logger)
    location = await _safe_extract_text(page, card, SELECTORS["card_location"], logger)
    employees_text = await _safe_extract_text(page, card, SELECTORS["card_employees"], logger)
    hourly_text = await _safe_extract_text(page, card, SELECTORS["card_hourly_rate"], logger)
    services_text = await _safe_extract_text(page, card, SELECTORS["card_services"], logger)
    rating_text = await _safe_extract_text(page, card, SELECTORS["card_rating"], logger)

    employees = await _extract_employees(employees_text) if employees_text else None
    hourly_rate = await _extract_hourly_rate(hourly_text) if hourly_text else None
    services = await _extract_services(services_text) if services_text else None
    rating = await _extract_rating_from_text(rating_text) if rating_text else None

    if location:
        location = re.sub(r"\s+", " ", location).strip()

    if services_text:
        services_list = re.split(r"\s*[,/•|]\s*|\s+•\s+", services_text)
        services_list = [s.strip() for s in services_list if len(s.strip()) > 1]
        services_str = ", ".join(services_list[:10]) if services_list else None
    else:
        services_str = None

    return {
        "company_name": name,
        "website": website,
        "goodfirms_profile_url": profile_url,
        "location": location,
        "employee_size": employees,
        "hourly_rate": hourly_rate,
        "services": services_str,
        "rating": rating,
        "source": "goodfirms",
        "scraped_at": datetime.now().isoformat(),
    }


async def _has_results(page: Page, logger) -> bool:
    try:
        for sel in SELECTORS["no_results"].split(", "):
            el = page.locator(sel).first
            if await el.count() > 0 and await el.is_visible(timeout=1000):
                logger.info("No results message detected via: %s", sel)
                return False
    except Exception:
        pass
    try:
        first_sel = SELECTORS["result_cards"].split(", ")[0]
        cards = page.locator(first_sel)
        count = await cards.count()
        if count > 0:
            return True
    except Exception:
        pass
    try:
        body_text = await page.locator("body").inner_text(timeout=3000)
        body_lower = body_text.lower()
        if "no results" in body_lower or "no companies" in body_lower or "nothing found" in body_lower:
            return False
    except Exception:
        pass
    return True


async def _go_to_next_page(page: Page, logger, cfg: Dict[str, Any], current_page: int) -> Optional[int]:
    timeout = cfg["browser"]["timeout"]
    min_delay = cfg["browser"]["min_delay"]
    max_delay = cfg["browser"]["max_delay"]

    try:
        await _scroll_slowly(page, logger, steps=4, delay=0.3)
    except Exception:
        pass

    btn = page.locator(SELECTORS["next_button"]).first
    try:
        if await btn.count() == 0:
            logger.info("Next button not found, ending pagination")
            return None
        if not await btn.is_visible(timeout=3000):
            logger.info("Next button not visible, ending pagination")
            return None
        is_disabled = await btn.get_attribute("disabled")
        if is_disabled:
            logger.info("Next button is disabled, ending pagination")
            return None
        class_attr = await btn.get_attribute("class")
        if class_attr and "disabled" in class_attr.lower():
            logger.info("Next button has disabled class, ending pagination")
            return None
    except Exception as e:
        logger.warning("Next button check failed: %s", e)
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
    except Exception as e:
        logger.warning("Failed to navigate to page %d: %s", current_page + 1, e)
        try:
            logger.info("Trying click-based navigation")
            await btn.click(timeout=timeout)
            await page.wait_for_load_state("networkidle", timeout=timeout)
            await asyncio.sleep(random.uniform(min_delay, max_delay))
            return current_page + 1
        except Exception as e2:
            logger.error("Click navigation also failed: %s", e2)
            return None


async def _extract_all_cards(page: Page, logger, cfg: Dict[str, Any], seen_urls: Set[str]) -> List[Dict[str, Any]]:
    extracted: List[Dict[str, Any]] = []
    min_delay = cfg["browser"]["min_delay"]
    max_delay = cfg["browser"]["max_delay"]

    for sel in SELECTORS["result_cards"].split(", "):
        try:
            cards = page.locator(sel)
            count = await cards.count()
            if count > 0:
                logger.info("Found %d cards using selector: %s", count, sel)
                for i in range(count):
                    try:
                        card = cards.nth(i)
                        if not await card.is_visible(timeout=2000):
                            continue
                        data = await _extract_card_data(page, card, logger, cfg)
                        if data is None:
                            logger.debug("Skipping card %d: no name extracted", i)
                            continue
                        dup_key = data["goodfirms_profile_url"] or data["company_name"]
                        if dup_key and dup_key in seen_urls:
                            logger.debug("Skipping duplicate: %s", dup_key)
                            continue
                        if dup_key:
                            seen_urls.add(dup_key)
                        extracted.append(data)
                        logger.debug("Extracted: %s | %s", data["company_name"], data["location"] or "N/A")
                    except Exception as e:
                        logger.warning("Error extracting card %d with %s: %s", i, sel, e)
                        continue
                if extracted:
                    break
        except Exception:
            continue

    if not extracted:
        logger.warning("No cards extracted with any selector")

    await asyncio.sleep(random.uniform(min_delay, max_delay))
    return extracted


_export_logger = logging.getLogger("scrapers.goodfirms")


async def _export_goodfirms_results(data: List[Dict[str, Any]], query: str, cfg: Dict[str, Any]) -> Optional[Path]:
    if not data:
        return None

    df = pd.DataFrame(data)
    export_format = cfg["export"]["format"]
    safe_query = re.sub(r"[^\w\-_]", "_", query.strip().lower())[:50]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{ts}_goodfirms_{safe_query}"
    ext = export_format.strip().lower()
    known = {"csv", "json", "parquet", "xlsx"}
    if ext not in known:
        _export_logger.warning("Unknown export format '%s', falling back to csv", ext)
        ext = "csv"
    out = BASE_DIR / "exports" / "goodfirms" / f"{filename}.{ext}"

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
                _export_logger.error("XLSX export failed for goodfirms: %s, falling back to CSV", xl_err)
                ext = "csv"
                out = out.with_suffix(".csv")
                df.to_csv(out, index=False, encoding="utf-8-sig")
        return out
    except Exception as e:
        _export_logger.error("Export failed for goodfirms: %s", e)
        return None


async def run_goodfirms_scraper(context: BrowserContext, logger, cfg: Dict[str, Any]) -> bool:
    page: Optional[Page] = None
    all_leads: List[Dict[str, Any]] = []
    seen_urls: Set[str] = set()
    current_page = 1
    timeout = cfg["browser"]["timeout"]
    min_delay = cfg["browser"]["min_delay"]
    max_delay = cfg["browser"]["max_delay"]
    retry_count = cfg["browser"]["retry_count"]

    print("\n" + "=" * 55)
    print("   GOODFIRMS.CO LEAD SCRAPER")
    print("=" * 55)
    query = input("Enter search query (e.g., 'software companies USA'): ").strip()
    if not query:
        logger.warning("Empty query provided")
        print("[ERROR] Query cannot be empty.")
        return False

    max_pages_str = input("Max pages to scrape (default 5): ").strip()
    try:
        max_pages = int(max_pages_str) if max_pages_str else 5
        if max_pages < 1:
            max_pages = 5
    except ValueError:
        max_pages = 5

    logger.info("Starting GoodFirms scrape | query='%s' | max_pages=%d", query, max_pages)

    try:
        page = await context.new_page()
        search_url = _build_search_url(query)
        logger.info("Search URL: %s", search_url)

        for attempt in range(1, retry_count + 1):
            try:
                logger.info("Navigation attempt %d/%d", attempt, retry_count)
                ok = await page.goto(search_url, timeout=timeout, wait_until="domcontentloaded")
                if ok is None:
                    raise Exception("Navigation returned None")
                await page.wait_for_load_state("networkidle", timeout=timeout)
                logger.info("Page loaded: %s", page.url)
                break
            except Exception as e:
                logger.warning("Navigation attempt %d failed: %s", attempt, e)
                if attempt < retry_count:
                    await asyncio.sleep(attempt * 3)
                else:
                    logger.error("All navigation attempts failed")
                    print("[ERROR] Could not load GoodFirms.co. Check your connection.")
                    return False

        await _accept_cookies(page, logger)
        await asyncio.sleep(random.uniform(min_delay, max_delay))

        has_results = await _has_results(page, logger)
        if not has_results:
            logger.info("No results found for query: %s", query)
            print(f"[INFO] No results found for '{query}'.")
            return True

        while current_page <= max_pages:
            logger.info("--- Processing page %d ---", current_page)
            print(f"\n[PAGE {current_page}] Scraping...")

            if current_page > 1:
                url = _build_page_url(search_url, current_page)
                for attempt in range(1, retry_count + 1):
                    try:
                        await page.goto(url, timeout=timeout, wait_until="domcontentloaded")
                        await page.wait_for_load_state("networkidle", timeout=timeout)
                        await _accept_cookies(page, logger)
                        await asyncio.sleep(random.uniform(min_delay, max_delay))
                        break
                    except Exception as e:
                        logger.warning("Page %d navigation attempt %d failed: %s", current_page, attempt, e)
                        if attempt < retry_count:
                            await asyncio.sleep(attempt * 3)
                        else:
                            logger.error("Failed to load page %d, stopping pagination", current_page)
                            current_page = max_pages + 1
                            break
                if current_page > max_pages:
                    break

            try:
                await _scroll_slowly(page, logger, steps=10, delay=0.35)
            except Exception as e:
                logger.warning("Scroll failed on page %d: %s", current_page, e)

            cards_data = await _extract_all_cards(page, logger, cfg, seen_urls)
            all_leads.extend(cards_data)
            logger.info(
                "Page %d: extracted %d leads (total: %d)",
                current_page,
                len(cards_data),
                len(all_leads),
            )
            print(f"         Extracted: {len(cards_data)} leads (total: {len(all_leads)})")

            if current_page >= max_pages:
                logger.info("Reached max_pages limit (%d)", max_pages)
                break

            next_page = await _go_to_next_page(page, logger, cfg, current_page)
            if next_page is None:
                logger.info("No more pages available")
                print("[INFO] No more pages available.")
                break

            current_page = next_page

        if all_leads:
            export_path = await _export_goodfirms_results(all_leads, query, cfg)
            if export_path:
                logger.info("Exported %d leads to %s", len(all_leads), export_path)
                print(f"\n[SUCCESS] Exported {len(all_leads)} leads to: {export_path}")
            else:
                logger.error("Export failed")
                print("\n[ERROR] Export failed.")
        else:
            logger.info("No leads extracted")
            print("\n[INFO] No leads were extracted.")

        return True

    except asyncio.CancelledError:
        logger.warning("GoodFirms scraper interrupted by user")
        if all_leads:
            export_path = await _export_goodfirms_results(all_leads, query, cfg)
            if export_path:
                print(f"\n[PARTIAL] Exported {len(all_leads)} leads to: {export_path}")
        print("\n[INTERRUPTED] Scraping stopped by user.")
        return False
    except PlaywrightTimeout as e:
        logger.error("Playwright timeout: %s", e)
        print(f"\n[ERROR] Timeout occurred: {e}")
        if all_leads:
            export_path = await _export_goodfirms_results(all_leads, query, cfg)
            if export_path:
                print(f"[PARTIAL] Exported {len(all_leads)} leads to: {export_path}")
        return False
    except Exception as e:
        logger.error("Unexpected GoodFirms scraper error: %s", e)
        print(f"\n[ERROR] Unexpected error: {e}")
        if all_leads:
            export_path = await _export_goodfirms_results(all_leads, query, cfg)
            if export_path:
                print(f"[PARTIAL] Exported {len(all_leads)} leads to: {export_path}")
        return False
    finally:
        if page:
            try:
                await page.close()
                logger.debug("GoodFirms scraper page closed")
            except Exception:
                pass
