import asyncio
import logging
import random
import re
from typing import Any

from playwright.async_api import Page

from backend.scrapers.base import safe_extract_attribute, safe_extract_text

logger = logging.getLogger("scrapers.linkedin")

FOUNDER_REGEX = re.compile(
    r"(?:Founded|Co-founded|Founder|Founded by|Co-founded by)\s*[:\-]?\s*([^.!]*)",
    re.IGNORECASE,
)
FOUNDER_NAME_REGEX = re.compile(r"(?:by\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})")
LINKEDIN_LOGIN_REGEX = re.compile(r"(sign.in|login|join.now|create.account)", re.IGNORECASE)
RATE_LIMIT_REGEX = re.compile(
    r"(too.many.requests|rate.limit|try.again.later|unusual.traffic|temporarily.blocked)",
    re.IGNORECASE,
)
SIZE_REGEX = re.compile(r"(\d[\d,]*\s*-\s*\d[\d,]*)\s*(employees?)", re.IGNORECASE)
SIZE_SINGLE_REGEX = re.compile(r"(\d[\d,]*\+?)\s*(employees?)", re.IGNORECASE)

SELECTORS = {
    "search_input": (
        "input[aria-label='Search'], input[placeholder='Search'], input[role='combobox']"
    ),
    "search_results": (
        "a[class*='search-result'], a[class*='company-result'], "
        "li[class*='search-result'], div[class*='entity-result'], "
        "div[class*='search-result']"
    ),
    "search_result_link": (
        "a[href*='/company/'], a[href*='/linkedin.com/company/'], "
        "a[class*='search-result__result-link']"
    ),
    "company_name": (
        "h1, h2[class*='name'], div[class*='company-name'], "
        "span[class*='org-name'], div[class*='org-top-card'] h1, "
        "[class*='top-card'] h1"
    ),
    "company_about": (
        "section[class*='about'], div[class*='about-us'], "
        "p[class*='description'], [class*='org-about'], "
        "meta[name='description']"
    ),
    "company_size": (
        "dd[class*='company-size'], span[class*='company-size'], "
        "dt:has-text('Company size') ~ dd, "
        "[class*='org-about'] dd, span:has-text('employees')"
    ),
    "login_wall": (
        "a[href*='signup'], a[href*='sign_in'], "
        "a[href*='join'], button:has-text('Sign in'), "
        "button:has-text('Join now'), form[action*='login']"
    ),
    "page_title": "title",
    "meta_description": "meta[name='description']",
}


def build_company_search_url(company_name: str) -> str:
    q = company_name.strip().lower().replace(" ", "%20")
    return f"https://www.linkedin.com/search/results/companies/?keywords={q}"


def extract_company_slug(url: str) -> str | None:
    match = re.search(r"linkedin\.com/company/([^/?]+)", url)
    return match.group(1) if match else None


def parse_founder_info(text: str) -> tuple:
    if not text:
        return None, None
    match = FOUNDER_REGEX.search(text)
    if not match:
        return None, None
    fragment = match.group(1).strip()
    if not fragment or len(fragment) < 3:
        return None, None
    name_match = FOUNDER_NAME_REGEX.search(fragment)
    if name_match:
        name = name_match.group(1).strip()
        role_text = fragment.replace(name, "").strip().lstrip(",").strip()
        role_text = re.sub(r"^and\s+", "", role_text).strip()
        role_text = re.sub(r"\s+", " ", role_text)
        role = role_text if role_text and len(role_text) < 80 else None
        return name, role
    return fragment, None


def parse_company_size(text: str) -> str | None:
    if not text:
        return None
    match = SIZE_REGEX.search(text)
    if match:
        return match.group(1).strip()
    match = SIZE_SINGLE_REGEX.search(text)
    if match:
        return match.group(1).strip() + " " + match.group(2)
    return text.strip() if any(c.isdigit() for c in text) else None


async def check_linkedin_barriers(page: Page) -> str | None:
    try:
        body_text = await page.locator("body").inner_text(timeout=5000)
        body_lower = body_text.lower()
        if RATE_LIMIT_REGEX.search(body_lower):
            logger.warning("LinkedIn rate limit detected")
            return "rate_limit"
        if LINKEDIN_LOGIN_REGEX.search(body_lower):
            logger.warning("LinkedIn login wall detected")
            return "login_required"
    except Exception:
        pass
    try:
        for sel in SELECTORS["login_wall"].split(", "):
            el = page.locator(sel).first
            if await el.count() > 0 and await el.is_visible(timeout=1000):
                logger.warning("Login wall element found: %s", sel)
                return "login_required"
    except Exception:
        pass
    try:
        current_url = page.url.lower()
        if "signup" in current_url or "sign_in" in current_url or "login" in current_url:
            return "login_required"
        if "checkpoint" in current_url and "challenge" in current_url:
            return "challenge"
    except Exception:
        pass
    return None


async def enrich_company(
    page: Page,
    company_name: str,
    website: str | None,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    from datetime import datetime

    timeout = cfg["browser"]["timeout"]
    retry_count = cfg["browser"]["retry_count"]

    result = {
        "input_company_name": company_name,
        "input_website": website or "",
        "linkedin_company_url": "",
        "founder_name": "",
        "founder_role": "",
        "company_size_from_linkedin": "",
        "matched_company_name": "",
        "enrichment_status": "skipped",
        "enriched_at": datetime.now().isoformat(),
    }

    search_name = website or company_name
    search_url = build_company_search_url(search_name)
    logger.info("Searching LinkedIn for: %s", search_name)

    for attempt in range(1, retry_count + 1):
        try:
            ok = await page.goto(search_url, timeout=timeout, wait_until="domcontentloaded")
            if ok is None:
                raise Exception("Navigation returned None")
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            break
        except Exception as e:
            logger.warning("Search navigation attempt %d failed: %s", attempt, e)
            if attempt < retry_count:
                await asyncio.sleep(attempt * 4)
            else:
                result["enrichment_status"] = "navigation_failed"
                return result

    barrier = await check_linkedin_barriers(page)
    if barrier:
        result["enrichment_status"] = barrier
        return result

    company_url = None
    for sel in SELECTORS["search_result_link"].split(", "):
        try:
            link_el = page.locator(sel).first
            if await link_el.count() > 0 and await link_el.is_visible(timeout=3000):
                href = await link_el.get_attribute("href")
                if href and "/company/" in href:
                    company_url = href.split("?")[0].rstrip("/") + "/"
                    extract_company_slug(company_url)
                    break
        except Exception:
            continue

    if not company_url:
        result["enrichment_status"] = "not_found"
        return result

    result["linkedin_company_url"] = company_url
    result["enrichment_status"] = "found_url"
    result["matched_company_name"] = search_name

    delay = random.uniform(cfg["browser"]["min_delay"], cfg["browser"]["max_delay"])
    await asyncio.sleep(delay)

    for attempt in range(1, retry_count + 1):
        try:
            ok = await page.goto(company_url, timeout=timeout, wait_until="domcontentloaded")
            if ok is None:
                raise Exception("Navigation returned None")
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            break
        except Exception as e:
            logger.warning("Company page navigation attempt %d failed: %s", attempt, e)
            if attempt < retry_count:
                await asyncio.sleep(attempt * 4)
            else:
                result["enrichment_status"] = "company_page_failed"
                return result

    barrier = await check_linkedin_barriers(page)
    if barrier:
        result["enrichment_status"] = barrier
        return result

    await asyncio.sleep(random.uniform(cfg["browser"]["min_delay"], cfg["browser"]["max_delay"]))

    try:
        matched_name = await safe_extract_text(page, page, SELECTORS["company_name"], logger)
        if matched_name:
            result["matched_company_name"] = matched_name
    except Exception:
        pass

    about_text = None
    try:
        about_text = await safe_extract_text(page, page, SELECTORS["company_about"], logger)
        if not about_text:
            about_text = await safe_extract_attribute(page, page, SELECTORS["meta_description"], "content", logger)
    except Exception:
        pass

    if about_text:
        founder_name, founder_role = parse_founder_info(about_text)
        if founder_name:
            result["founder_name"] = founder_name
            result["founder_role"] = founder_role or ""

    try:
        size_text = await safe_extract_text(page, page, SELECTORS["company_size"], logger)
        if size_text:
            parsed_size = parse_company_size(size_text)
            if parsed_size:
                result["company_size_from_linkedin"] = parsed_size
    except Exception:
        pass

    if about_text:
        for pattern in [r"(\d[\d,]*\s*-\s*\d[\d,]*)\s+employees", r"(\d[\d,]*\+?)\s+employees"]:
            match = re.search(pattern, about_text, re.IGNORECASE)
            if match:
                result["company_size_from_linkedin"] = match.group(0).strip()
                break

    result["enrichment_status"] = "enriched"
    return result
