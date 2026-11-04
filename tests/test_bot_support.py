"""Formatting, i18n, rate limiter, services and registry."""

from __future__ import annotations

import string
from decimal import Decimal
from typing import Any

import pytest

from aggregator.bot.formatting import (
    PAGE_SIZE,
    TELEGRAM_MESSAGE_LIMIT,
    clamp_page,
    format_empty,
    format_money,
    format_results,
    page_count,
)
from aggregator.bot.i18n import CATALOGS, EN, RU, Texts
from aggregator.config import Settings
from aggregator.domain.cities import SELECTABLE_CITIES, City
from aggregator.domain.models import ExpandedQuery, Filters
from aggregator.query import QueryExpander
from aggregator.search.filters import build_view
from aggregator.search.models import SearchOutcome, SourceStatus
from aggregator.search.orchestrator import SearchOrchestrator
from aggregator.services.quota import check_quota
from aggregator.services.ratelimit import SlidingWindowRateLimiter
from aggregator.services.search_service import InvalidQueryError, SearchService
from aggregator.services.users import (
    InMemoryUserStore,
    UserProfile,
    UserService,
    guess_language,
)
from aggregator.sources.base import SourceError
from aggregator.sources.registry import build_registry
from factories import make_listing

# --- i18n ---------------------------------------------------------------------------------


def placeholders(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


def test_catalogs_have_identical_keys_and_placeholders() -> None:
    assert EN.keys() == RU.keys()
    for key in EN:
        assert placeholders(EN[key]) == placeholders(RU[key]), key


def test_every_selectable_city_and_unknown_is_translated() -> None:
    for catalog in CATALOGS.values():
        for city in (*SELECTABLE_CITIES, City.UNKNOWN):
            assert f"city.{city.value}" in catalog


def test_texts_fall_back_to_english_for_unknown_languages_and_missing_keys() -> None:
    assert Texts("de")("btn_next") == EN["btn_next"]
    assert Texts("ru")("btn_next") == RU["btn_next"]


def test_texts_missing_key_in_english_is_a_loud_bug() -> None:
    with pytest.raises(KeyError):
        Texts("en")("no.such.key")


@pytest.mark.parametrize(
    ("code", "expected"), [("ru", "ru"), ("uk-UA", "ru"), ("de", "en"), (None, "en")]
)
def test_guess_language(code: str | None, expected: str) -> None:
    assert guess_language(code) == expected


# --- formatting ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("amount", "expected"),
    [("520", "€520"), ("1234.5", "€1,234.50"), ("99.999", "€100"), ("0.5", "€0.50")],
)
def test_format_money(amount: str, expected: str) -> None:
    assert format_money(Decimal(amount)) == expected


def test_paging_math() -> None:
    assert [page_count(n) for n in (0, 1, 5, 6, 11)] == [1, 1, 1, 2, 3]
    assert [clamp_page(p, 11) for p in (-3, 0, 2, 9)] == [0, 0, 2, 2]


def outcome_for(listings: list[Any], **kwargs: Any) -> SearchOutcome:
    return SearchOutcome(
        query=ExpandedQuery(original="iphone 13", normalized="iphone 13"),
        city=City.LIMASSOL,
        listings=listings,
        statuses=[SourceStatus(name="bazaraki", ok=True, count=len(listings))],
        **kwargs,
    )


def test_results_stay_within_telegram_limit_even_with_huge_titles_and_urls() -> None:
    listings = [
        make_listing("X" * 500, price=100 + i, external_id="e" * 90 + str(i)) for i in range(40)
    ]
    outcome = outcome_for(listings)
    view = build_view(outcome.listings, Filters())
    for page in range(page_count(len(view.listings))):
        text = format_results(Texts("en"), outcome, view, page)
        assert len(text) <= TELEGRAM_MESSAGE_LIMIT
        assert text.count("<a ") == text.count("</a>")  # never a half-cut tag


def test_card_shows_original_currency_and_missing_price() -> None:
    listings = [
        make_listing("Bike A", price=100, currency="GBP", external_id="a"),
        make_listing("Bike B", price=None, external_id="b"),
    ]
    outcome = outcome_for(listings)
    text = format_results(Texts("en"), outcome, build_view(listings, Filters()), 0)
    assert "(100 GBP)" in text
    assert "price not listed" in text
    assert "without a price" in text


def test_bazaraki_dates_are_marked_approximate_but_telegram_dates_are_not() -> None:
    listings = [
        make_listing("Bike A", source="bazaraki", external_id="a"),
        make_listing("Bike B", source="telegram", external_id="b"),
    ]
    text = format_results(Texts("en"), outcome_for(listings), build_view(listings, Filters()), 0)
    cards_text = text.split("Listings")[1]
    meta_lines = {
        "Bazaraki" if "Bazaraki" in line else "Telegram": line
        for line in cards_text.splitlines()
        if "posted " in line
    }
    assert "posted ~" in meta_lines["Bazaraki"]
    assert "posted " in meta_lines["Telegram"] and "posted ~" not in meta_lines["Telegram"]


def test_unreliable_stats_are_flagged() -> None:
    listings = [make_listing("Bike", price=100, external_id="a")]
    text = format_results(Texts("en"), outcome_for(listings), build_view(listings, Filters()), 0)
    assert "unreliable" in text


def test_page_size_is_five() -> None:
    listings = [make_listing(f"Bike {i}", external_id=str(i)) for i in range(12)]
    text = format_results(Texts("en"), outcome_for(listings), build_view(listings, Filters()), 1)
    assert "page 2/3" in text
    assert text.count("<a ") == PAGE_SIZE


def test_best_deals_block_can_be_hidden() -> None:
    prices = [100, 100, 100, 100, 100, 100, 30]  # one clear bargain among 7 priced listings
    listings = [
        make_listing(f"Bike {i}", price=p, external_id=f"{i}") for i, p in enumerate(prices)
    ]
    outcome = outcome_for(listings)
    view = build_view(listings, Filters())
    assert view.best_deals  # the data really does produce a deal

    shown = format_results(Texts("en"), outcome, view, 0)
    hidden = format_results(Texts("en"), outcome, view, 0, show_deals=False)
    assert "Best deals" in shown
    assert "Best deals" not in hidden
    assert "Median" in hidden and "Listings" in hidden  # the rest of the message is unchanged


def test_best_deals_are_off_by_default_in_settings() -> None:
    assert settings().show_best_deals is False
    assert settings(show_best_deals=True).show_best_deals is True


def test_format_empty_distinguishes_total_failure_from_no_matches() -> None:
    failed = SearchOutcome(
        query=ExpandedQuery(original="x", normalized="x"),
        city=City.ALL_CYPRUS,
        statuses=[SourceStatus(name="bazaraki", ok=False, error="x")],
    )
    assert "couldn't reach" in format_empty(Texts("en"), failed)
    assert "Nothing found" in format_empty(Texts("en"), outcome_for([]))


# --- rate limiter -------------------------------------------------------------------------


def test_rate_limiter_allows_up_to_the_limit_then_reports_wait_time() -> None:
    now = [0.0]
    limiter = SlidingWindowRateLimiter(2, 60, clock=lambda: now[0])
    assert limiter.hit(1) is None
    now[0] = 10
    assert limiter.hit(1) is None
    now[0] = 20
    assert limiter.hit(1) == pytest.approx(40)  # first hit frees up at t=60
    assert limiter.hit(2) is None  # per user
    now[0] = 61
    assert limiter.hit(1) is None


# --- services -----------------------------------------------------------------------------


async def test_user_service_creates_updates_and_validates() -> None:
    service = UserService(InMemoryUserStore())
    user = await service.ensure_user(7, "ru")
    assert (user.language, user.city) == ("ru", None)

    assert (await service.set_language(7, "en")).language == "en"
    assert (await service.set_city(7, City.PAPHOS)).city is City.PAPHOS
    assert (await service.ensure_user(7, "ru")).language == "en"  # existing prefs win

    with pytest.raises(ValueError, match="unsupported"):
        await service.set_language(7, "el")
    with pytest.raises(ValueError, match="selectable"):
        await service.set_city(7, City.UNKNOWN)


def test_check_quota_is_the_monetization_seam() -> None:
    assert check_quota(UserProfile(telegram_id=1)).allowed
    blocked = check_quota(UserProfile(telegram_id=1, is_allowed=False))
    assert not blocked.allowed and blocked.reason == "user_blocked"


class RecordingLog:
    def __init__(self, error: Exception | None = None) -> None:
        self.rows: list[tuple[Any, ...]] = []
        self.error = error

    async def add(self, *row: Any) -> None:
        if self.error:
            raise self.error
        self.rows.append(row)


class OneSource:
    name = "bazaraki"

    def __init__(self, result: Any) -> None:
        self.result = result

    async def search(self, *_: Any) -> list[Any]:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def make_service(source: Any, search_log: Any = None) -> SearchService:
    return SearchService(
        QueryExpander(llm=None),
        SearchOrchestrator([source], source_timeout_seconds=1),
        search_log,
        max_query_length=20,
    )


@pytest.mark.parametrize(
    ("text", "reason"),
    [("", "empty"), ("  \n ", "empty"), ("x" * 21, "too_long"), ("!!! 🙂", "no_content")],
)
def test_search_service_validation(text: str, reason: str) -> None:
    with pytest.raises(InvalidQueryError) as info:
        make_service(OneSource([])).validate_query(text)
    assert info.value.reason == reason


async def test_search_service_defaults_to_all_cyprus_logs_and_tolerates_log_failures() -> None:
    log = RecordingLog()
    service = make_service(OneSource([make_listing("iPhone 13", external_id="1")]), log)
    outcome = await service.search(UserProfile(id=3, telegram_id=1), "  iphone   13 ")
    assert outcome.city is City.ALL_CYPRUS
    assert log.rows == [(3, "iphone 13", "all", 1, outcome.duration_ms)]

    broken = make_service(OneSource([]), RecordingLog(error=ConnectionError("db")))
    assert (await broken.search(UserProfile(telegram_id=1), "iphone")).listings == []


async def test_search_service_survives_a_failing_source() -> None:
    outcome = await make_service(OneSource(SourceError("x"))).search(
        UserProfile(telegram_id=1), "iphone"
    )
    assert outcome.all_failed


# --- registry -----------------------------------------------------------------------------


def settings(**kw: Any) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[call-arg]


async def test_registry_builds_enabled_sources_in_order() -> None:
    registry = build_registry(settings(enabled_sources=["telegram", "bazaraki"]), object())  # type: ignore[arg-type]
    try:
        assert registry.names == ["telegram", "bazaraki"]
    finally:
        await registry.aclose()


async def test_registry_skips_telegram_without_a_database_and_unknown_names() -> None:
    registry = build_registry(settings(enabled_sources=["telegram", "nope", "bazaraki"]), None)
    try:
        assert registry.names == ["bazaraki"]
    finally:
        await registry.aclose()


def test_facebook_needs_its_feature_flag() -> None:
    assert build_registry(settings(enabled_sources=["facebook"]), None).names == []
    flagged = build_registry(settings(enabled_sources=[], enable_facebook_marketplace=True), None)
    assert flagged.names == ["facebook"]
