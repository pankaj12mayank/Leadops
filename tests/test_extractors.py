import logging
from pathlib import Path
import sys
from unittest.mock import AsyncMock, Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.scrapers.base import (
    accept_cookies,
    build_page_url,
    extract_rating_from_text,
    extract_employees,
    extract_hourly_rate,
    extract_services,
)


class TestBuildPageUrl:
    def test_page_1_returns_base_url(self):
        assert build_page_url("https://example.com", 1) == "https://example.com"

    def test_page_0_returns_base_url(self):
        assert build_page_url("https://example.com", 0) == "https://example.com"

    def test_page_2_appends_query_param(self):
        assert build_page_url("https://example.com", 2) == "https://example.com?page=2"

    def test_existing_query_uses_ampersand(self):
        assert build_page_url("https://example.com?q=test", 2) == "https://example.com?q=test&page=2"

    def test_handles_no_scheme(self):
        assert build_page_url("example.com/search", 3) == "example.com/search?page=3"


class TestExtractRating:
    @pytest.mark.asyncio
    async def test_x_out_of_5(self):
        assert await extract_rating_from_text("4.5 / 5") == 4.5

    @pytest.mark.asyncio
    async def test_out_of_5(self):
        assert await extract_rating_from_text("3.8 out of 5") == 3.8

    @pytest.mark.asyncio
    async def test_plain_number(self):
        assert await extract_rating_from_text("4.2") == 4.2

    @pytest.mark.asyncio
    async def test_rating_label(self):
        assert await extract_rating_from_text("Rating: 4.0") == 4.0

    @pytest.mark.asyncio
    async def test_none_returns_none(self):
        assert await extract_rating_from_text(None) is None

    @pytest.mark.asyncio
    async def test_empty_string(self):
        assert await extract_rating_from_text("") is None

    @pytest.mark.asyncio
    async def test_no_match(self):
        assert await extract_rating_from_text("no rating here") is None


class TestExtractEmployees:
    @pytest.mark.asyncio
    async def test_range_format(self):
        result = await extract_employees("50 - 100 Employees")
        assert result is not None

    @pytest.mark.asyncio
    async def test_single_value_with_plus(self):
        result = await extract_employees("1000+ Employees")
        assert result == "1000+ Employees"

    @pytest.mark.asyncio
    async def test_none_returns_none(self):
        assert await extract_employees(None) is None

    @pytest.mark.asyncio
    async def test_empty_string(self):
        assert await extract_employees("") is None


class TestExtractHourlyRate:
    @pytest.mark.asyncio
    async def test_dollar_range_per_hr(self):
        result = await extract_hourly_rate("$50 - $80 /hr")
        assert result == "$50-$80/hr"

    @pytest.mark.asyncio
    async def test_single_dollar_per_hr(self):
        assert await extract_hourly_rate("$75 /hr") == "$75/hr"

    @pytest.mark.asyncio
    async def test_dollar_range(self):
        assert await extract_hourly_rate("$100 - $150") == "$100-$150"

    @pytest.mark.asyncio
    async def test_none_returns_none(self):
        assert await extract_hourly_rate(None) is None


class TestExtractServices:
    @pytest.mark.asyncio
    async def test_cleans_whitespace(self):
        result = await extract_services("SEO   Marketing  PPC")
        assert result == "SEO Marketing PPC"

    @pytest.mark.asyncio
    async def test_cleans_comma_spacing(self):
        result = await extract_services("SEO ,Marketing,PPC")
        assert result is not None
        assert ", " in result

    @pytest.mark.asyncio
    async def test_none_returns_none(self):
        assert await extract_services(None) is None

    @pytest.mark.asyncio
    async def test_short_string_returns_none(self):
        assert await extract_services("a") is None


class TestAcceptCookies:
    @pytest.mark.asyncio
    async def test_empty_selectors_returns_false(self):
        page = AsyncMock()
        first_loc = AsyncMock()
        first_loc.count = AsyncMock(return_value=0)
        locator_mock = AsyncMock()
        locator_mock.first = first_loc
        page.locator.return_value = locator_mock
        result = await accept_cookies(page, logging.getLogger("test"), "button.btn")
        assert result is False

    @pytest.mark.asyncio
    async def test_found_button_clicks(self):
        # Create the locator chain: page.locator() -> locator -> locator.first -> first_loc
        first_loc = AsyncMock()
        first_loc.count = AsyncMock(return_value=1)
        first_loc.click = AsyncMock()

        locator = AsyncMock()
        locator.first = first_loc

        # Page.locator is a method that returns locator when called
        page = AsyncMock()
        page.locator = Mock(return_value=locator)

        result = await accept_cookies(page, logging.getLogger("test"), "button.btn")
        assert result is True


class TestBuildPageUrlEdgeCases:
    def test_trailing_slash(self):
        assert build_page_url("https://example.com/", 2) == "https://example.com/?page=2"

    def test_multi_page_with_hash(self):
        assert build_page_url("https://example.com#section", 3) == "https://example.com#section?page=3"
