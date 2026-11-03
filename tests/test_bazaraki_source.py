from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

from aggregator.cache import InMemoryTTLCache
from aggregator.domain.cities import City
from aggregator.domain.models import ExpandedQuery, Filters, Listing
from aggregator.sources.base import ListingSource, SourceError
from aggregator.sources.bazaraki.client import BazarakiClient
from aggregator.sources.bazaraki.source import BazarakiSource, search_terms

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 3, tzinfo=UTC)
UA = "TestBot/0.0"


def html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def make_query(*variants: str) -> ExpandedQuery:
    return ExpandedQuery(original="iphone 13", normalized="iphone 13", variants=list(variants))


class Sleeps:
    """Records requested sleeps instead of waiting (rate limit + backoff)."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def make_source(sleeps: Sleeps, **kwargs: int) -> tuple[BazarakiSource, BazarakiClient]:
    client = BazarakiClient(
        user_agent=UA, min_interval_seconds=1.0, backoff_base_seconds=2.0, sleep=sleeps
    )
    cache: InMemoryTTLCache[list[Listing]] = InMemoryTTLCache()
    source = BazarakiSource(client, cache, now=lambda: NOW, **kwargs)
    return source, client


def test_source_satisfies_the_protocol() -> None:
    source, _ = make_source(Sleeps())
    assert isinstance(source, ListingSource)
    assert source.name == "bazaraki"


def test_search_terms_dedupe_and_cap() -> None:
    query = make_query("IPHONE 13", "айфон 13", "apple iphone 13")
    assert search_terms(query, 2) == ["iphone 13", "айфон 13"]
    assert search_terms(query, 10) == ["iphone 13", "айфон 13", "apple iphone 13"]
    assert search_terms(query, 0) == ["iphone 13"]


@respx.mock
async def test_fetches_follows_pagination_and_sends_clear_user_agent() -> None:
    route = respx.get("https://www.bazaraki.com/search/").mock(
        side_effect=[
            httpx.Response(200, text=html("bazaraki_search.html")),
            httpx.Response(200, text=html("bazaraki_last_page.html")),
        ]
    )
    source, client = make_source(Sleeps())
    listings = await source.search(make_query(), City.ALL_CYPRUS, Filters())

    assert [item.external_id for item in listings] == [
        "1000001",
        "1000002",
        "1000003",
        "1000004",
        "1000005",
    ]
    assert route.call_count == 2
    first, second = (call.request for call in route.calls)
    assert first.url.params["q"] == "iphone 13"
    assert "page" not in first.url.params
    assert second.url.params["page"] == "2"
    assert first.headers["User-Agent"] == UA
    await client.aclose()


@respx.mock
async def test_city_scopes_the_path_and_fills_unknown_locations() -> None:
    route = respx.get("https://www.bazaraki.com/search/lemesos-district-limassol/").mock(
        return_value=httpx.Response(200, text=html("bazaraki_single_page.html"))
    )
    source, client = make_source(Sleeps(), max_pages=1)
    listings = await source.search(make_query(), City.LIMASSOL, Filters())
    assert route.call_count == 1
    assert len(listings) == 1
    await client.aclose()


@respx.mock
async def test_results_are_cached_per_term_and_city() -> None:
    route = respx.get("https://www.bazaraki.com/search/").mock(
        return_value=httpx.Response(200, text=html("bazaraki_single_page.html"))
    )
    source, client = make_source(Sleeps())
    await source.search(make_query(), None, Filters())
    await source.search(make_query(), City.ALL_CYPRUS, Filters())
    assert route.call_count == 1  # None and All Cyprus share a cache entry
    await client.aclose()


@respx.mock
async def test_requests_are_rate_limited_and_variants_are_deduped() -> None:
    respx.get("https://www.bazaraki.com/search/").mock(
        return_value=httpx.Response(200, text=html("bazaraki_single_page.html"))
    )
    sleeps = Sleeps()
    source, client = make_source(sleeps)
    listings = await source.search(make_query("айфон 13"), None, Filters())
    assert [item.external_id for item in listings] == ["1000005"]  # same ad from both terms
    # two requests; the real clock barely moves so the second must be throttled
    assert any(abs(s - 1.0) < 0.5 for s in sleeps.calls)
    await client.aclose()


@respx.mock
async def test_retries_transient_errors_with_backoff() -> None:
    route = respx.get("https://www.bazaraki.com/search/").mock(
        side_effect=[
            httpx.Response(503),
            httpx.ConnectError("boom"),
            httpx.Response(200, text=html("bazaraki_single_page.html")),
        ]
    )
    sleeps = Sleeps()
    source, client = make_source(sleeps)
    listings = await source.search(make_query(), None, Filters())
    assert len(listings) == 1
    assert route.call_count == 3
    assert 2.0 in sleeps.calls and 4.0 in sleeps.calls  # exponential backoff
    await client.aclose()


@respx.mock
async def test_retry_after_header_is_honoured_and_capped() -> None:
    respx.get("https://www.bazaraki.com/search/").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "999"}),
            httpx.Response(200, text=html("bazaraki_single_page.html")),
        ]
    )
    sleeps = Sleeps()
    source, client = make_source(sleeps)
    await source.search(make_query(), None, Filters())
    assert 30.0 in sleeps.calls
    await client.aclose()


@respx.mock
async def test_gives_up_after_max_attempts() -> None:
    route = respx.get("https://www.bazaraki.com/search/").mock(return_value=httpx.Response(502))
    source, client = make_source(Sleeps())
    with pytest.raises(SourceError, match="3 attempts"):
        await source.search(make_query(), None, Filters())
    assert route.call_count == 3
    await client.aclose()


@respx.mock
async def test_blocked_is_not_retried_or_worked_around() -> None:
    route = respx.get("https://www.bazaraki.com/search/").mock(return_value=httpx.Response(403))
    source, client = make_source(Sleeps())
    with pytest.raises(SourceError, match="403"):
        await source.search(make_query(), None, Filters())
    assert route.call_count == 1
    await client.aclose()
