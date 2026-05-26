import asyncio
import logging
import random
import re
from datetime import datetime
from typing import Any

from playwright.async_api import Page

from backend.scrapers.base import safe_extract_href, safe_extract_text

logger = logging.getLogger("scrapers.maps")

PHONE_REGEX = re.compile(r"(\+?\d{1,3}[\s\-.]?\(?\d{1,4}\)?[\s\-.]?\d{1,4}[\s\-.]?\d{1,9})")
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


def build_search_url(query: str, cfg: dict[str, Any]) -> str:
    base = cfg.get("scraping", {}).get("maps_base_url", "https://www.google.com/maps/search/")
    q = query.strip().lower().replace(" ", "+")
    return f"{base}{q}/"


async def check_captcha(page: Page) -> bool:
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
        logger.debug("Captcha check failed")
    return False


async def scroll_feed(page: Page, container, steps: int = 5) -> bool:
    try:
        if container:
            for _ in range(steps):
                await container.evaluate("el => el.scrollBy(0, 200)")
                await asyncio.sleep(random.uniform(0.15, 0.4))
        else:
            for _ in range(steps):
                await page.evaluate("window.scrollBy(0, 200)")
                await asyncio.sleep(random.uniform(0.15, 0.4))
        return True
    except Exception:
        logger.debug("Scroll failed")
        return False


async def extract_single_item(page: Page, item) -> dict[str, Any] | None:
    name = None
    try:
        name = await safe_extract_text(page, item, SELECTORS["business_name"], logger)
        if not name:
            try:
                name = await item.get_attribute("aria-label")
            except Exception:
                pass
        if not name:
            return None
        name = re.sub(r"\s+", " ", name).strip()
    except Exception:
        logger.warning("Failed to extract item name")
        return None

    website = await safe_extract_href(page, item, SELECTORS["website"], logger)
    category = await safe_extract_text(page, item, SELECTORS["category_element"], logger)

    rating = None
    reviews = None
    try:
        aria_label = await item.get_attribute("aria-label")
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
    except Exception:
        pass

    phone = None
    address = None
    try:
        full_text = await item.inner_text()
        if full_text:
            lines = [ln.strip() for ln in full_text.split("\n") if ln.strip()]
            phone_match = PHONE_REGEX.search(full_text)
            if phone_match:
                phone = phone_match.group(1).strip()
            non_name = [ln for ln in lines if ln != name]
            if website:
                non_name = [ln for ln in non_name if website not in ln]
            if phone:
                non_name = [ln for ln in non_name if phone not in ln]
            if category:
                non_name = [ln for ln in non_name if category not in ln]
            if non_name:
                address = re.sub(r"\s+", " ", non_name[0]).strip()
    except Exception:
        logger.debug("Failed to extract full text")

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


async def extract_all_items(page: Page, seen_names: set[str]) -> list[dict[str, Any]]:
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
                    data = await extract_single_item(page, item)
                    if data is None:
                        continue
                    dup_key = (data["business_name"] or "").lower().strip()
                    if not dup_key or dup_key in seen_names or dup_key in seen_in_session:
                        continue
                    seen_in_session.add(dup_key)
                    extracted.append(data)
                except Exception:
                    continue
            if extracted:
                break
        except Exception:
            continue

    seen_names.update(seen_in_session)
    return extracted
