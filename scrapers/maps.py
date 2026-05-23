import asyncio
import logging
import random
import re
from datetime import datetime
from typing import Any

import pandas as pd
from playwright.async_api import (
    BrowserContext,
    Page,
)
from playwright.async_api import (
    TimeoutError as PlaywrightTimeout,
)

from .base import (
    export_dataframe_to_file,
    safe_extract_href,
    safe_extract_text,
)

logger = logging.getLogger("scrapers.maps")

PHONE_REGEX = re.compile(
    r"(\+?\d{1,3}[\s\-.]?\(?\d{1,4}\)?[\s\-.]?\d{1,4}[\s\-.]?\d{1,9})"
)
RATING_REGEX = re.compile(r"([\d.]+)\s*(star|rating|★)", re.IGNORECASE)
REVIEWS_REGEX = re.compile(r"\(?\s*([\d,]+)\s*(review|reviews)\)?", re.IGNORECASE)

SELECTORS = {
    "cookie_accept": (
        "button:has-text('Accept all'), button:has-text('Accept'), "
        "button:has-text('Got it'), button:has-text('Reject all'), "
        "button:has-text('I agree'), div[role='button']:has-text('Accept')"
    ),
    "feed_container": "div[role='feed']",
    "result_items": (
        "div[role='feed'] > div > div[jsaction], "
        "div[role='feed'] > div, "
        "a[href*='maps.google.com']:has(h3), "
        "div[role='article']"
    ),
    "business_name": (
        "div[role='heading'], h3, h2, "
        "a[aria-label], [class*='fontHeadline'], "
        "span[class*='title']"
    ),
    "website": (
        "a[href^='http']:not([href*='google']):not([href*='maps']):not([href*='youtube'])"
    ),
    "rating_element": (
        "[aria-label*='star'], [aria-label*='rating'], "
        "span[aria-label*='stars'], [class*='star-display']"
    ),
    "reviews_element": (
        "span:has-text('review'), [aria-label*='review'], "
        "[class*='review-count']"
    ),
    "category_element": "[class*='category'], [class*='type'], [class*='tag']",
}


def _build_search_url(query: str, cfg: dict[str, Any]) -> str:
    base = cfg.get("scraping", {}).get("maps_base_url", "https://www.google.com/maps/search/")
    q = query.strip().lower().replace(" ", "+")
    return f"{base}{q}/"


async def _check_captcha(page: Page, logger) -> bool:
    try:
        title = await page.title()
        if "captcha" in title.lower():
            logger.warning("Captcha page detected: %s", title)
            return True
        body_text = await page.locator("body").inner_text(timeout=5000)
        clues = ["captcha", "unusual traffic", "verify you're human", "automated queries"]
        for clue in clues:
            if clue in body_text.lower():
                logger.warning("Anti-bot detection triggered: '%s'", clue)
                return True
    except Exception:
        logger.debug("Captcha check failed (page/body not ready)")
    return False


async def _get_feed_item_count(page: Page) -> int:
    try:
        items = page.locator(SELECTORS["result_items"])
        return await items.count()
    except Exception:
        logger.debug("Failed to count feed items")
        return 0


async def _find_feed_container(page: Page, logger) -> Any | None:
    try:
        feed = page.locator(SELECTORS["feed_container"])
        if await feed.count() > 0:
            logger.debug("Found feed container via role='feed'")
            return feed.first
    except Exception:
        logger.debug("Feed container check failed")
    return None


async def _scroll_feed_human(page: Page, container, logger, cfg: dict[str, Any]) -> bool:
    min_delay = cfg["browser"]["min_delay"]
    max_delay = cfg["browser"]["max_delay"]

    try:
        before_count = await _get_feed_item_count(page)
        scraping_cfg = cfg.get("scraping", {})
        sa_min = scraping_cfg.get("maps_scroll_amount_min", 400)
        sa_max = scraping_cfg.get("maps_scroll_amount_max", 700)
        ss_min = scraping_cfg.get("maps_scroll_steps_min", 3)
        ss_max = scraping_cfg.get("maps_scroll_steps_max", 6)
        scroll_amount = random.randint(sa_min, sa_max)
        steps = random.randint(ss_min, ss_max)
        step_amount = scroll_amount // steps

        if container:
            for i in range(steps):
                await container.evaluate(
                    f"el => el.scrollBy(0, {step_amount})"
                )
                await asyncio.sleep(random.uniform(0.15, 0.4))
        else:
            for i in range(steps):
                await page.evaluate(f"window.scrollBy(0, {step_amount})")
                await asyncio.sleep(random.uniform(0.15, 0.4))

        await asyncio.sleep(random.uniform(min_delay, max_delay) * 0.6)

        await page.wait_for_load_state("domcontentloaded", timeout=5000)
        try:
            await page.wait_for_load_state("networkidle", timeout=3000)
        except Exception:
            logger.debug("networkidle timed out during scroll")

        after_count = await _get_feed_item_count(page)
        return after_count > before_count

    except Exception as e:
        logger.warning("Feed scroll failed: %s", e)
        return False


async def _scroll_to_top(page: Page, container, logger) -> None:
    try:
        if container:
            await container.evaluate("el => el.scrollTo(0, 0)")
        else:
            await page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(0.3)
    except Exception:
        logger.debug("Scroll to top failed")


async def _scroll_to_bottom(page: Page, container, logger) -> None:
    try:
        if container:
            await container.evaluate(
                "el => el.scrollTo(0, el.scrollHeight)"
            )
        else:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(0.5)
    except Exception:
        logger.debug("Scroll to bottom failed")


async def _get_aria_label(page: Page, parent, logger) -> str | None:
    try:
        label = await parent.get_attribute("aria-label")
        if label:
            return label.strip()
    except Exception:
        logger.warning("Failed to get aria-label")
    return None


async def _extract_phone_from_text(text: str) -> str | None:
    if not text:
        return None
    match = PHONE_REGEX.search(text)
    if match:
        phone = re.sub(r"[\s\-.]", "", match.group(1))
        if len(phone) >= 7:
            return match.group(1).strip()
    return None


async def _extract_rating_and_reviews(page: Page, item, logger) -> tuple:
    rating = None
    reviews = None

    aria_label = await _get_aria_label(page, item, logger)
    if aria_label:
        rm = RATING_REGEX.search(aria_label)
        if rm:
            try:
                rating = float(rm.group(1))
            except ValueError:
                pass
        rvm = REVIEWS_REGEX.search(aria_label)
        if rvm:
            try:
                reviews = int(rvm.group(1).replace(",", ""))
            except ValueError:
                pass

    if rating is None:
        rating_text = await safe_extract_text(
            page, item, SELECTORS["rating_element"], logger
        )
        if rating_text:
            rm = RATING_REGEX.search(rating_text)
            if rm:
                try:
                    rating = float(rm.group(1))
                except ValueError:
                    pass
            if rating is None:
                fm = re.search(r"([\d.]+)", rating_text)
                if fm:
                    try:
                        rating = float(fm.group(1))
                    except ValueError:
                        pass

    if reviews is None:
        reviews_text = await safe_extract_text(
            page, item, SELECTORS["reviews_element"], logger
        )
        if reviews_text:
            rvm = REVIEWS_REGEX.search(reviews_text)
            if rvm:
                try:
                    reviews = int(rvm.group(1).replace(",", ""))
                except ValueError:
                    pass
            if reviews is None:
                fm = re.search(r"(\d[\d,]*)", reviews_text)
                if fm:
                    try:
                        reviews = int(fm.group(1).replace(",", ""))
                    except ValueError:
                        pass

    return rating, reviews


async def _extract_single_item(page: Page, item, logger) -> dict[str, Any] | None:
    name = None
    try:
        name = await safe_extract_text(
            page, item, SELECTORS["business_name"], logger
        )
        if not name:
            name = await _get_aria_label(page, item, logger)
        if not name:
            return None
        name = re.sub(r"\s+", " ", name).strip()
    except Exception:
        logger.warning("Failed to extract item name")
        return None

    website = await safe_extract_href(page, item, SELECTORS["website"], logger)
    rating, reviews = await _extract_rating_and_reviews(page, item, logger)
    category = await safe_extract_text(
        page, item, SELECTORS["category_element"], logger
    )

    full_text = None
    try:
        full_text = await item.inner_text()
    except Exception:
        logger.debug("Failed to get inner_text, trying textContent")
        try:
            full_text = await page.evaluate(
                "el => el.textContent", item
            )
        except Exception:
            logger.debug("Failed to get textContent fallback")

    phone = None
    address = None

    if full_text:
        lines = [ln.strip() for ln in full_text.split("\n") if ln.strip()]
        phone = await _extract_phone_from_text(full_text)

        non_name = [ln for ln in lines if ln not in (name or "")]
        if rating is not None or reviews is not None:
            rating_line = None
            for ln in non_name:
                if "★" in ln or "star" in ln.lower() or "review" in ln.lower():
                    rating_line = ln
                    break
            if rating_line and rating_line in non_name:
                non_name.remove(rating_line)

        if website:
            non_name = [ln for ln in non_name if website not in ln]

        if phone:
            non_name = [ln for ln in non_name if phone not in ln]

        if category:
            non_name = [ln for ln in non_name if category not in ln]

        if non_name:
            address = non_name[0]
            address = re.sub(r"\s+", " ", address).strip()

    if category:
        category = re.sub(r"\s+", " ", category).strip()

    return {
        "business_name": name,
        "website": website,
        "phone": phone,
        "address": address,
        "rating": rating,
        "reviews_count": reviews,
        "category": category,
        "source": "google_maps",
        "scraped_at": datetime.now().isoformat(),
    }


async def _extract_all_results(page: Page, logger, cfg: dict[str, Any], seen_names: set[str]) -> list[dict[str, Any]]:
    extracted: list[dict[str, Any]] = []
    seen_in_session: set[str] = set()

    for sel in SELECTORS["result_items"].split(", "):
        try:
            items = page.locator(sel)
            count = await items.count()
            if count == 0:
                continue
            logger.info("Found %d items with selector: %s", count, sel)
            for i in range(count):
                try:
                    item = items.nth(i)
                    if not await item.is_visible(timeout=1000):
                        continue
                    data = await _extract_single_item(page, item, logger)
                    if data is None:
                        logger.debug("Skipping item %d: no name", i)
                        continue
                    dup_key = (data["business_name"] or "").lower().strip()
                    if not dup_key:
                        continue
                    if dup_key in seen_names or dup_key in seen_in_session:
                        logger.debug("Skipping duplicate: %s", dup_key)
                        continue
                    seen_in_session.add(dup_key)
                    extracted.append(data)
                    logger.debug("Extracted: %s | rating=%s", data["business_name"], data["rating"])
                except Exception as e:
                    logger.debug("Item %d extraction skipped: %s", i, e)
                    continue
            if extracted:
                break
        except Exception:
            logger.warning("Selector iteration failed in extraction")
            continue

    seen_names.update(seen_in_session)
    return extracted


async def run_maps_scraper(
    context: BrowserContext, logger, cfg: dict[str, Any], query: str, max_cycles: int = 30
) -> bool:
    page: Page | None = None
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
        search_url = _build_search_url(query, cfg)
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
                    logger.debug("networkidle timed out, continuing with domcontentloaded")
                logger.info("Page loaded: %s", page.url)
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

        if await _check_captcha(page, logger):
            logger.error("Captcha or rate-limit detected")
            print("\n[ERROR] Google is showing a captcha or rate-limit page.")
            print("[ERROR] Open the browser manually, complete the captcha,")
            print("        then restart the scraper.")
            return False

        feed_container = await _find_feed_container(page, logger)
        if feed_container is None:
            logger.warning("Feed container not found via role='feed'")

        current_count = await _get_feed_item_count(page)
        if current_count == 0:
            logger.info("No results visible initially, scrolling to trigger load")
            await _scroll_to_bottom(page, feed_container, logger)
            await asyncio.sleep(2)
            current_count = await _get_feed_item_count(page)
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
                cards_data = await _extract_all_results(page, logger, cfg, seen_names)
            except Exception as e:
                logger.warning("Extraction failed on cycle %d: %s", cycle, e)
                await asyncio.sleep(random.uniform(min_delay, max_delay))
                continue

            new_in_cycle = [d for d in cards_data if d["business_name"].lower().strip() not in seen_names]
            all_leads.extend(cards_data)
            logger.info(
                "Cycle %d: extracted %d leads (new: %d, total: %d)",
                cycle,
                len(cards_data),
                len(new_in_cycle),
                len(all_leads),
            )
            print(f"         Extracted: {len(cards_data)} leads (total: {len(all_leads)})")

            if await _check_captcha(page, logger):
                logger.warning("Captcha detected during scrolling")
                print("\n[WARNING] Captcha detected. Stopping.")
                break

            if len(new_in_cycle) == 0:
                consecutive_empty += 1
                logger.info(
                    "No new items found (consecutive_empty=%d/%d)",
                    consecutive_empty,
                    max_empty_scrolls,
                )
                if consecutive_empty >= max_empty_scrolls:
                    logger.info("No new items after %d consecutive scrolls, stopping", max_empty_scrolls)
                    print(f"\n[INFO] No new results after {max_empty_scrolls} scrolls. Ending.")
                    break
            else:
                consecutive_empty = 0

            logger.info("Scrolling for more results...")
            print("         Scrolling for more...")

            scrolled = await _scroll_feed_human(page, feed_container, logger, cfg)

            if not scrolled:
                logger.info("Scroll didn't produce new items immediately")
                await asyncio.sleep(random.uniform(min_delay * 0.5, min_delay))

            await asyncio.sleep(random.uniform(min_delay * 0.3, min_delay * 0.7))

        if all_leads:
            export_path = export_dataframe_to_file(pd.DataFrame(all_leads), f"maps_{query[:50]}", "maps", cfg, logger)
            if export_path:
                logger.info("Exported %d leads to %s", len(all_leads), export_path)
                print(f"\n[SUCCESS] Exported {len(all_leads)} leads to: {export_path}")
            else:
                logger.error("Export failed")
                print("\n[ERROR] Export failed.")
        else:
            logger.info("No leads extracted")
            print("\n[INFO] No leads were extracted.")
        _exported_ok = True
        return True

    except asyncio.CancelledError:
        logger.warning("Maps scraper interrupted by user")
        print("\n[INTERRUPTED] Scraping stopped by user.")
        return False
    except PlaywrightTimeout as e:
        logger.error("Playwright timeout: %s", e)
        print(f"\n[ERROR] Timeout occurred: {e}")
        return False
    except Exception as e:
        logger.error("Unexpected Maps scraper error: %s", e)
        print(f"\n[ERROR] Unexpected error: {e}")
        return False
    finally:
        try:
            if not _exported_ok and isinstance(all_leads, list) and len(all_leads) > 0:
                export_path = export_dataframe_to_file(
                    pd.DataFrame(all_leads), f"maps_{query[:50]}", "maps", cfg, logger,
                )
                if export_path:
                    print(f"\n[PARTIAL] Exported {len(all_leads)} leads to: {export_path}")
        except Exception:
            logger.warning("Failed to export partial data in finally block")
    if page:
            try:
                await page.close()
                logger.debug("Maps scraper page closed")
            except Exception:
                logger.debug("Failed to close Maps page")
