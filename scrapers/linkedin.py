import asyncio
import logging
import random
import re
from datetime import datetime
from pathlib import Path
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
    BASE_DIR,
    export_dataframe_to_file,
    safe_extract_attribute,
    safe_extract_text,
)

logger = logging.getLogger("scrapers.linkedin")

FOUNDER_REGEX = re.compile(
    r"(?:Founded|Co-founded|Founder|Founded by|Co-founded by)\s*[:\-]?\s*([^.!]*)",
    re.IGNORECASE,
)
FOUNDER_NAME_REGEX = re.compile(
    r"(?:by\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})"
)
LINKEDIN_LOGIN_REGEX = re.compile(
    r"(sign.in|login|join.now|create.account)", re.IGNORECASE
)
RATE_LIMIT_REGEX = re.compile(
    r"(too.many.requests|rate.limit|try.again.later|unusual.traffic|temporarily.blocked)",
    re.IGNORECASE,
)
SIZE_REGEX = re.compile(
    r"(\d[\d,]*\s*-\s*\d[\d,]*)\s*(employees?)",
    re.IGNORECASE,
)
SIZE_SINGLE_REGEX = re.compile(
    r"(\d[\d,]*\+?)\s*(employees?)",
    re.IGNORECASE,
)

SELECTORS = {
    "search_input": (
        "input[aria-label='Search'], input[placeholder='Search'], "
        "input[role='combobox']"
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
        "[class*='org-about'] dd, "
        "span:has-text('employees')"
    ),
    "login_wall": (
        "a[href*='signup'], a[href*='sign_in'], "
        "a[href*='join'], button:has-text('Sign in'), "
        "button:has-text('Join now'), form[action*='login']"
    ),
    "page_title": "title",
    "meta_description": "meta[name='description']",
}


def _build_company_search_url(company_name: str) -> str:
    q = company_name.strip().lower().replace(" ", "%20")
    return f"https://www.linkedin.com/search/results/companies/?keywords={q}"


def _build_company_page_url(slug: str) -> str:
    slug = slug.strip().strip("/")
    return f"https://www.linkedin.com/company/{slug}/"


def _extract_company_slug(url: str) -> str | None:
    match = re.search(r"linkedin\.com/company/([^/?]+)", url)
    if match:
        return match.group(1)
    return None


def _parse_founder_info(text: str) -> tuple:
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


def _parse_company_size(text: str) -> str | None:
    if not text:
        return None
    match = SIZE_REGEX.search(text)
    if match:
        return match.group(1).strip()
    match = SIZE_SINGLE_REGEX.search(text)
    if match:
        return match.group(1).strip() + " " + match.group(2)
    return text.strip() if any(c.isdigit() for c in text) else None


async def _check_linkedin_barriers(page: Page, logger) -> str | None:
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
        logger.debug("Failed to check LinkedIn body text for barriers")
    try:
        for sel in SELECTORS["login_wall"].split(", "):
            el = page.locator(sel).first
            if await el.count() > 0 and await el.is_visible(timeout=1000):
                logger.warning("Login wall element found: %s", sel)
                return "login_required"
    except Exception:
        logger.debug("Failed to check login wall elements")
    try:
        current_url = page.url.lower()
        if "signup" in current_url or "sign_in" in current_url or "login" in current_url:
            logger.warning("Redirected to login page: %s", current_url)
            return "login_required"
        if "checkpoint" in current_url and "challenge" in current_url:
            logger.warning("LinkedIn challenge page: %s", current_url)
            return "challenge"
    except Exception:
        logger.debug("Failed to check URL for barriers")
    return None


async def _enrich_company(
    page: Page,
    company_name: str,
    website: str | None,
    logger,
    cfg: dict[str, Any],
) -> dict[str, Any]:
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
    search_url = _build_company_search_url(search_name)
    logger.info("Searching LinkedIn for: %s", search_name)
    print(f"\n   Searching LinkedIn for: {search_name}")

    for attempt in range(1, retry_count + 1):
        try:
            ok = await page.goto(search_url, timeout=timeout, wait_until="domcontentloaded")
            if ok is None:
                raise Exception("Navigation returned None")
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                logger.debug("networkidle timeout during search navigation")
            break
        except Exception as e:
            logger.warning("Search navigation attempt %d failed: %s", attempt, e)
            if attempt < retry_count:
                await asyncio.sleep(attempt * 4)
            else:
                logger.error("All search navigation attempts failed for: %s", search_name)
                result["enrichment_status"] = "navigation_failed"
                return result

    barrier = await _check_linkedin_barriers(page, logger)
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
                    _extract_company_slug(company_url)
                    logger.info("Found company link: %s", company_url)
                    break
        except Exception:
            logger.warning("Failed to check search result link")
            continue

    if not company_url:
        logger.info("No company search result found for: %s", search_name)
        result["enrichment_status"] = "not_found"
        return result

    result["linkedin_company_url"] = company_url
    result["enrichment_status"] = "found_url"
    result["matched_company_name"] = search_name

    sc = cfg.get("scraping", {})
    delay = random.uniform(
        sc.get("linkedin_min_company_delay", 4.0),
        sc.get("linkedin_max_company_delay", 7.0),
    )
    logger.info("Waiting %.1f seconds before navigating to company page", delay)
    await asyncio.sleep(delay)

    for attempt in range(1, retry_count + 1):
        try:
            ok = await page.goto(company_url, timeout=timeout, wait_until="domcontentloaded")
            if ok is None:
                raise Exception("Navigation returned None")
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                logger.debug("networkidle timeout during company navigation")
            logger.info("Loaded company page: %s", company_url)
            break
        except Exception as e:
            logger.warning("Company page navigation attempt %d failed: %s", attempt, e)
            if attempt < retry_count:
                await asyncio.sleep(attempt * 4)
            else:
                logger.error("Failed to load company page: %s", company_url)
                result["enrichment_status"] = "company_page_failed"
                return result

    barrier = await _check_linkedin_barriers(page, logger)
    if barrier:
        result["enrichment_status"] = barrier
        return result

    sc = cfg.get("scraping", {})
    await asyncio.sleep(random.uniform(
        sc.get("linkedin_min_page_delay", 2.0),
        sc.get("linkedin_max_page_delay", 4.0),
    ))

    try:
        matched_name = await safe_extract_text(page, page, SELECTORS["company_name"], logger)
        if matched_name:
            result["matched_company_name"] = matched_name
            logger.info("Matched company name: %s", matched_name)
    except Exception:
        logger.warning("Failed to extract matched company name")

    about_text = None
    try:
        about_text = await safe_extract_text(page, page, SELECTORS["company_about"], logger)
        if not about_text:
            about_text = await safe_extract_attribute(
                page, page, SELECTORS["meta_description"], "content", logger
            )
    except Exception:
        logger.warning("Failed to extract about text")

    if about_text:
        founder_name, founder_role = _parse_founder_info(about_text)
        if founder_name:
            result["founder_name"] = founder_name
            result["founder_role"] = founder_role or ""
            logger.info("Found founder: %s (%s)", founder_name, founder_role or "N/A")

    try:
        size_text = await safe_extract_text(page, page, SELECTORS["company_size"], logger)
        if size_text:
            parsed_size = _parse_company_size(size_text)
            if parsed_size:
                result["company_size_from_linkedin"] = parsed_size
                logger.info("Found company size: %s", parsed_size)
    except Exception:
        logger.warning("Failed to extract company size")

    if about_text:
        for pattern in [r"(\d[\d,]*\s*-\s*\d[\d,]*)\s+employees", r"(\d[\d,]*\+?)\s+employees"]:
            match = re.search(pattern, about_text, re.IGNORECASE)
            if match:
                result["company_size_from_linkedin"] = match.group(0).strip()
                break

    result["enrichment_status"] = "enriched"
    return result


async def run_linkedin_enrichment(
    context: BrowserContext, logger, cfg: dict[str, Any], csv_path: Path | None = None
) -> bool:
    page: Page | None = None
    all_results: list[dict[str, Any]] = []
    if csv_path is None:
        csv_path = BASE_DIR / "exports" / "linkedin" / "input_companies.csv"
    input_path = csv_path

    if not input_path.exists():
        print(f"\n[ERROR] File not found: {input_path}")
        logger.error("CSV file not found: %s", input_path)
        print("[INFO] Create a CSV with columns: company_name, website (website optional)")
        return False

    try:
        df = pd.read_csv(input_path)
        df.columns = [c.strip().lower() for c in df.columns]
    except Exception as e:
        logger.error("Failed to read CSV: %s", e)
        print(f"\n[ERROR] Could not read CSV: {e}")
        return False

    name_col = None
    website_col = None
    for col in df.columns:
        if col in ("company_name", "name", "company", "business_name", "business"):
            name_col = col
        if col in ("website", "url", "domain", "site", "web"):
            website_col = col

    if name_col is None:
        logger.error("No company name column found in CSV")
        print(f"\n[ERROR] No company name column found. Columns: {list(df.columns)}")
        print("[INFO] Expected: 'company_name' or 'name' column")
        return False

    total = len(df)
    logger.info("Loaded %d companies from %s", total, input_path)
    print(f"\n[INFO] Loaded {total} companies from {input_path}")
    print(f"[INFO] Name column: '{name_col}'" + (f", Website column: '{website_col}'" if website_col else ""))

    logger.info("Starting LinkedIn enrichment for %d companies", total)
    print("\nStarting LinkedIn enrichment. This will run slowly on purpose.")

    try:
        page = await context.new_page()

        delay_between = max(cfg["browser"]["max_delay"] * 2, 8.0)
        enriched_count = 0
        skipped_count = 0

        for idx, row in df.iterrows():
            company_name = str(row[name_col]).strip()
            website = str(row[website_col]).strip() if website_col and pd.notna(row.get(website_col, "")) else ""
            if not company_name or company_name.lower() in ("nan", "none", ""):
                logger.warning("Row %d: empty company name, skipping", idx)
                skipped_count += 1
                continue

            print(f"\n{'=' * 50}")
            print(f"  [{idx + 1}/{total}] {company_name}")
            print(f"{'=' * 50}")

            result = await _enrich_company(page, company_name, website, logger, cfg)
            all_results.append(result)

            if result["enrichment_status"] == "enriched":
                enriched_count += 1
                print(f"  [OK] LinkedIn URL: {result['linkedin_company_url']}")
                if result["founder_name"]:
                    print(f"  [OK] Founder: {result['founder_name']} ({result['founder_role'] or 'N/A'})")
                if result["company_size_from_linkedin"]:
                    print(f"  [OK] Size: {result['company_size_from_linkedin']}")
            elif result["enrichment_status"] == "not_found":
                print("  [SKIP] No LinkedIn company page found")
            elif result["enrichment_status"] in ("login_required", "rate_limit", "challenge"):
                logger.warning("LinkedIn barrier at company %d: %s", idx, result["enrichment_status"])
                print(f"\n[STOP] LinkedIn {result['enrichment_status']} detected.")
                if result["enrichment_status"] == "login_required":
                    print("       Please log in to LinkedIn via Setup Browser Session (option 1).")
                elif result["enrichment_status"] == "rate_limit":
                    print("       LinkedIn rate-limited the request. Wait and try again later.")
                else:
                    print("       LinkedIn challenge page. Complete it in the browser.")
                break
            else:
                print(f"  [SKIP] {result['enrichment_status']}")

            if idx < total - 1:
                jitter = random.uniform(0.8, 1.2)
                wait_time = delay_between * jitter
                logger.info("Waiting %.1f seconds before next company", wait_time)
                if wait_time >= 3:
                    print(f"  Waiting {wait_time:.0f} seconds before next company...")
                await asyncio.sleep(wait_time)

        print(f"\n{'=' * 50}")
        print(f"  RESULTS: {enriched_count} enriched, {skipped_count} skipped")
        print(f"  Total processed: {len(all_results)}")
        print(f"{'=' * 50}")

        if all_results:
            export_path = export_dataframe_to_file(
                pd.DataFrame(all_results), "linkedin_enrichment", "linkedin", cfg, logger,
            )
            if export_path:
                logger.info("Exported %d results to %s", len(all_results), export_path)
                print(f"\n[SUCCESS] Exported {len(all_results)} results to: {export_path}")
            else:
                logger.error("Export failed")
                print("\n[ERROR] Export failed.")
        else:
            logger.info("No results to export")
            print("\n[INFO] No results to export.")

        return True

    except asyncio.CancelledError:
        logger.warning("LinkedIn enrichment interrupted by user")
        if all_results:
            export_path = export_dataframe_to_file(
                pd.DataFrame(all_results), "linkedin_enrichment", "linkedin", cfg, logger,
            )
            if export_path:
                print(f"\n[PARTIAL] Exported {len(all_results)} results to: {export_path}")
        print("\n[INTERRUPTED] Enrichment stopped by user.")
        return False
    except PlaywrightTimeout as e:
        logger.error("Playwright timeout: %s", e)
        print(f"\n[ERROR] Timeout occurred: {e}")
        if all_results:
            export_path = export_dataframe_to_file(
                pd.DataFrame(all_results), "linkedin_enrichment", "linkedin", cfg, logger,
            )
            if export_path:
                print(f"[PARTIAL] Exported {len(all_results)} results to: {export_path}")
        return False
    except Exception as e:
        logger.error("Unexpected LinkedIn enrichment error: %s", e)
        print(f"\n[ERROR] Unexpected error: {e}")
        if all_results:
            export_path = export_dataframe_to_file(
                pd.DataFrame(all_results), "linkedin_enrichment", "linkedin", cfg, logger,
            )
            if export_path:
                print(f"[PARTIAL] Exported {len(all_results)} results to: {export_path}")
        return False
    finally:
        if page:
            try:
                await page.close()
                logger.debug("LinkedIn enrichment page closed")
            except Exception:
                logger.debug("Failed to close LinkedIn page")
