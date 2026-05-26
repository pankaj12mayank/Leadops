import asyncio
import logging
import random
import re
from datetime import datetime
from typing import Any

from playwright.async_api import Page

from backend.scrapers.base import (
    retry_extraction,
    safe_extract_href,
    safe_extract_text,
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
        "a[class*='title'], a[class*='profile-link'], a[class*='name']"
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
        "span:has-text('/hr'), [class*='pricing'] span, [class*='rate'] span"
    ),
    "card_services": (
        "[class*='service'], [class*='focus'], "
        "[class*='category'], [class*='expertise'], [class*='offer']"
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
}


def build_search_url(query: str, cfg: dict[str, Any]) -> str:
    base = cfg.get("scraping", {}).get("clutch_base_url", "https://clutch.co/search?q=")
    q = query.strip().lower().replace(" ", "+")
    return f"{base}{q}"


def prepend_domain(href: str) -> str:
    if href.startswith("/"):
        return "https://clutch.co" + href
    return href


async def extract_card_data(page: Page, card, cfg: dict[str, Any]) -> dict[str, Any] | None:
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
    profile_url = prepend_domain(raw_profile) if raw_profile else None
    raw_website = await safe_extract_href(page, card, SELECTORS["card_website"], logger)
    website = prepend_domain(raw_website) if raw_website else None
    location = await safe_extract_text(page, card, SELECTORS["card_location"], logger)
    rating_text = await safe_extract_text(page, card, SELECTORS["card_rating"], logger)

    if location:
        location = re.sub(r"\s+", " ", location).strip()

    rating = None
    if rating_text:
        match = re.search(r"([\d.]+)\s*/\s*5", rating_text)
        if match:
            try:
                rating = float(match.group(1))
            except ValueError:
                pass

    return {
        "company_name": name,
        "website": website,
        "clutch_profile_url": profile_url,
        "location": location,
        "rating": rating,
        "source": "clutch",
        "scraped_at": datetime.now().isoformat(),
    }


async def extract_all_cards(page: Page, cfg: dict[str, Any], seen_urls: set[str]) -> list[dict[str, Any]]:
    extracted: list[dict[str, Any]] = []
    min_delay = cfg["browser"]["min_delay"]
    max_delay = cfg["browser"]["max_delay"]

    for sel in SELECTORS["result_cards"].split(", "):
        try:
            cards = page.locator(sel)
            count = await cards.count()
            if count == 0:
                continue
            logger.info("Found %d cards using selector: %s", count, sel)

            for i in range(count):
                try:
                    card = cards.nth(i)
                    if not await card.is_visible(timeout=2000):
                        continue
                    data = await retry_extraction(
                        extract_card_data(page, card, cfg),
                        logger,
                        label=f"card {i}",
                        namespace="clutch",
                    )
                    if data is None:
                        continue
                    dup_key = data.get("clutch_profile_url") or data.get("company_name")
                    if dup_key and dup_key in seen_urls:
                        continue
                    if dup_key:
                        seen_urls.add(dup_key)
                    extracted.append(data)
                except Exception:
                    logger.debug("Card %d extraction skipped", i)

            if extracted:
                break
        except Exception:
            continue

    if not extracted:
        logger.warning("No cards extracted with any selector")

    await asyncio.sleep(random.uniform(min_delay, max_delay))
    return extracted
