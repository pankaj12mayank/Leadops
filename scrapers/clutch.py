import asyncio
import logging
import random
import re
from datetime import datetime
from typing import Any

import pandas as pd
from playwright.async_api import BrowserContext, Page
from playwright.async_api import TimeoutError as PlaywrightTimeout

from .base import (
    accept_cookies,
    export_dataframe_to_file,
    extract_employees,
    extract_hourly_rate,
    extract_rating_from_text,
    go_to_next_page,
    has_results,
    navigate_with_retry,
    retry_extraction,
    safe_extract_href,
    safe_extract_text,
    scroll_slowly,
)

logger = logging.getLogger("scrapers.clutch")

SELECTORS = {
    "cookie_accept": (
        "button:has-text('Accept'), button:has-text('Got it'), "
        "button:has-text('Allow All'), button:has-text('Agree')"
    ),
    "result_cards": (
        "div[class*='provider'], article[class*='provider'], "
        "div[class*='search-result'], div[class*='company-card'], "
        "div[class*='result-item'], li[class*='provider']"
    ),
    "card_name": (
        "a[class*='company-name'], a[class*='provider-name'], "
        "a[class*='title'], h3 a, h2 a, a[class*='profile-name']"
    ),
    "card_website": (
        "a[class*='website'], a[class*='visit'], "
        "a[href*='http']:not([href*='clutch.co']):not([href*='clutch'])"
    ),
    "card_profile": (
        "a[class*='company-name'], a[class*='provider-name'], "
        "a[class*='title'], a[class*='profile-link'], "
        "a[class*='name']"
    ),
    "card_location": (
        "[class*='location'], [class*='address'], span[class*='locality'], "
        "[class*='city'], div[class*='location'] span"
    ),
    "card_employees": (
        "[class*='employee'], [class*='size'], "
        "span:has-text('Employees') ~ span, "
        "[class*='employees'] span, [class*='count']"
    ),
    "card_hourly_rate": (
        "[class*='rate'], [class*='hourly'], "
        "span:has-text('/hr'), [class*='pricing'] span, "
        "[class*='rate'] span"
    ),
    "card_services": (
        "[class*='service'], [class*='focus'], "
        "[class*='category'], [class*='expertise'], "
        "[class*='offer']"
    ),
    "card_rating": (
        "[class*='rating'], span[class*='score'], "
        "[class*='stars'], [class*='review-rating']"
    ),
    "next_button": (
        "a[rel='next'], button[aria-label='Next'], "
        "a:has-text('Next'), a:has-text('next'), "
        "li.pager-next a, li.next a, button:has-text('Next')"
    ),
    "no_results": (
        "div:has-text('No results'), p:has-text('no results'), "
        "div:has-text('no companies'), div:has-text('Nothing found')"
    ),
    "results_count": "[class*='result-count'], [class*='search-count'], span[class*='count']",
}


def _build_search_url(query: str, cfg: dict[str, Any]) -> str:
    base = cfg.get("scraping", {}).get("clutch_base_url", "https://clutch.co/search?q=")
    q = query.strip().lower().replace(" ", "+")
    return f"{base}{q}"


def _prepend_domain(href: str) -> str:
    if href.startswith("/"):
        return "https://clutch.co" + href
    return href


async def _extract_card_data(page: Page, card, cfg: dict[str, Any]) -> dict[str, Any] | None:
    try:
        if not await card.is_visible(timeout=2000):
            return None
    except Exception:
        logger.debug("Card visibility check failed")
        return None

    try:
        name = await safe_extract_text(page, card, SELECTORS["card_name"], logger)
        if not name:
            return None
        name = re.sub(r"\s+", " ", name).strip()
    except Exception:
        logger.warning("Failed to extract card name")
        return None

    raw_profile = await safe_extract_href(page, card, SELECTORS["card_profile"], logger)
    profile_url = _prepend_domain(raw_profile) if raw_profile else None
    raw_website = await safe_extract_href(page, card, SELECTORS["card_website"], logger)
    website = _prepend_domain(raw_website) if raw_website else None
    location = await safe_extract_text(page, card, SELECTORS["card_location"], logger)
    employees_text = await safe_extract_text(page, card, SELECTORS["card_employees"], logger)
    hourly_text = await safe_extract_text(page, card, SELECTORS["card_hourly_rate"], logger)
    services_text = await safe_extract_text(page, card, SELECTORS["card_services"], logger)
    rating_text = await safe_extract_text(page, card, SELECTORS["card_rating"], logger)

    employees = await extract_employees(employees_text) if employees_text else None
    hourly_rate = await extract_hourly_rate(hourly_text) if hourly_text else None
    rating = await extract_rating_from_text(rating_text) if rating_text else None

    if location:
        location = re.sub(r"\s+", " ", location).strip()

    services_str = None
    if services_text:
        services_list = re.split(r"\s*[,/]\s*|\s+•\s+", services_text)
        services_list = [s.strip() for s in services_list if len(s.strip()) > 1]
        services_str = ", ".join(services_list[:8]) if services_list else None

    return {
        "company_name": name,
        "website": website,
        "clutch_profile_url": profile_url,
        "location": location,
        "employee_size": employees,
        "hourly_rate": hourly_rate,
        "services": services_str,
        "rating": rating,
        "source": "clutch",
        "scraped_at": datetime.now().isoformat(),
    }


async def _extract_all_cards(page: Page, cfg: dict[str, Any], seen_urls: set[str]) -> list[dict[str, Any]]:
    extracted: list[dict[str, Any]] = []
    min_delay = cfg["browser"]["min_delay"]
    max_delay = cfg["browser"]["max_delay"]
    concurrency = cfg["browser"].get("concurrency", 1)

    for sel in SELECTORS["result_cards"].split(", "):
        try:
            cards = page.locator(sel)
            count = await cards.count()
            if count == 0:
                continue
            logger.info("Found %d cards using selector: %s", count, sel)

            async def _try_card(i: int):
                try:
                    card = cards.nth(i)
                    if not await card.is_visible(timeout=2000):
                        return None
                    return await retry_extraction(
                        _extract_card_data(page, card, cfg),
                        logger,
                        label=f"card {i}",
                        namespace="clutch",
                    )
                except Exception:
                    logger.warning("Card extraction failed in _try_card")
                    return None

            sem = asyncio.Semaphore(concurrency)

            async def _bounded(i: int):
                async with sem:
                    return await _try_card(i)

            results = await asyncio.gather(*[_bounded(i) for i in range(count)], return_exceptions=True)

            for i, data in enumerate(results):
                if isinstance(data, Exception) or data is None:
                    continue
                dup_key = data.get("clutch_profile_url") or data.get("company_name")
                if dup_key and dup_key in seen_urls:
                    continue
                if dup_key:
                    seen_urls.add(dup_key)
                extracted.append(data)
                logger.debug("Extracted: %s | %s", data["company_name"], data["location"] or "N/A")

            if extracted:
                break
        except Exception:
            logger.warning("Selector iteration failed in extraction")
            continue

    if not extracted:
        logger.warning("No cards extracted with any selector, trying fallback extraction")

    await asyncio.sleep(random.uniform(min_delay, max_delay))
    return extracted


async def run_clutch_scraper(
    context: BrowserContext, logger, cfg: dict[str, Any], query: str, max_pages: int = 5
) -> bool:
    page: Page | None = None
    all_leads: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    current_page = 1
    logger.info("Starting Clutch scrape | query='%s' | max_pages=%d", query, max_pages)

    try:
        page = await context.new_page()
        search_url = _build_search_url(query, cfg)
        logger.info("Search URL: %s", search_url)

        if not await navigate_with_retry(page, search_url, logger, cfg):
            logger.error("All navigation attempts failed")
            print("[ERROR] Could not load Clutch.co. Check your connection.")
            return False

        await accept_cookies(page, logger, SELECTORS["cookie_accept"])
        await asyncio.sleep(random.uniform(cfg["browser"]["min_delay"], cfg["browser"]["max_delay"]))

        if not await has_results(page, logger, SELECTORS["no_results"], SELECTORS["result_cards"]):
            logger.info("No results found for query: %s", query)
            print(f"[INFO] No results found for '{query}'.")
            return True

        while current_page <= max_pages:
            logger.info("--- Processing page %d ---", current_page)
            print(f"\n[PAGE {current_page}] Scraping...")

            if current_page > 1:
                url = f"{search_url}&page={current_page}"
                if not await navigate_with_retry(page, url, logger, cfg):
                    logger.error("Failed to load page %d, stopping pagination", current_page)
                    break
                await accept_cookies(page, logger, SELECTORS["cookie_accept"])
                await asyncio.sleep(random.uniform(cfg["browser"]["min_delay"], cfg["browser"]["max_delay"]))

            try:
                await scroll_slowly(page, logger, steps=10, delay=0.35)
            except Exception as e:
                logger.warning("Scroll failed on page %d: %s", current_page, e)

            cards_data = await _extract_all_cards(page, cfg, seen_urls)
            all_leads.extend(cards_data)
            logger.info("Page %d: extracted %d leads (total: %d)", current_page, len(cards_data), len(all_leads))
            print(f"         Extracted: {len(cards_data)} leads (total: {len(all_leads)})")

            if current_page >= max_pages:
                logger.info("Reached max_pages limit (%d)", max_pages)
                break

            next_page = await go_to_next_page(page, logger, cfg, current_page, SELECTORS["next_button"])
            if next_page is None:
                logger.info("No more pages available")
                print("[INFO] No more pages available.")
                break
            current_page = next_page

        if all_leads:
            export_path = export_dataframe_to_file(
                pd.DataFrame(all_leads), f"clutch_{query[:50]}", "clutch", cfg, logger
            )
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
        logger.warning("Clutch scraper interrupted by user")
        if all_leads:
            export_dataframe_to_file(pd.DataFrame(all_leads), f"clutch_{query[:50]}", "clutch", cfg, logger)
            print(f"\n[PARTIAL] Exported {len(all_leads)} leads.")
        print("\n[INTERRUPTED] Scraping stopped by user.")
        return False
    except PlaywrightTimeout as e:
        logger.error("Playwright timeout: %s", e)
        print(f"\n[ERROR] Timeout occurred: {e}")
        if all_leads:
            export_dataframe_to_file(pd.DataFrame(all_leads), f"clutch_{query[:50]}", "clutch", cfg, logger)
            print(f"[PARTIAL] Exported {len(all_leads)} leads.")
        return False
    except Exception as e:
        logger.error("Unexpected Clutch scraper error: %s", e)
        print(f"\n[ERROR] Unexpected error: {e}")
        if all_leads:
            export_dataframe_to_file(pd.DataFrame(all_leads), f"clutch_{query[:50]}", "clutch", cfg, logger)
            print(f"[PARTIAL] Exported {len(all_leads)} leads.")
        return False
    finally:
        if page:
            try:
                await page.close()
                logger.debug("Clutch scraper page closed")
            except Exception:
                logger.debug("Failed to close Clutch page")
