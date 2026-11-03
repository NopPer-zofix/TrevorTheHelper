from __future__ import annotations

import asyncio
from typing import Any

from aggregator.domain.cities import City
from aggregator.domain.models import ExpandedQuery, Filters, Listing
from aggregator.search.models import SourceStatus
from aggregator.search.orchestrator import SearchOrchestrator
from aggregator.sources.base import ListingSource, SourceError
from aggregator.sources.facebook import FacebookMarketplaceSource
from factories import make_listing

QUERY = ExpandedQuery(
    original="iphone 13",
    normalized="iphone 13",
    variants=["айфон 13"],
    negative_terms=["case", "чехол"],
)


class FakeSource:
    def __init__(
        self, name: str, result: list[Listing] | Exception | None = None, delay: float = 0
    ):
        self.name = name
        self.result = result or []
        self.delay = delay
        self.calls: list[tuple[ExpandedQuery, City | None, Filters]] = []

    async def search(
        self, query: ExpandedQuery, city: City | None, filters: Filters
    ) -> list[Listing]:
        self.calls.append((query, city, filters))
        if self.delay:
            await asyncio.sleep(self.delay)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def orchestrator(*sources: Any, timeout: float = 1.0) -> SearchOrchestrator:
    return SearchOrchestrator(list(sources), source_timeout_seconds=timeout)


async def test_merges_sources_and_reports_per_source_counts() -> None:
    baz = FakeSource("bazaraki", [make_listing("iPhone 13", source="bazaraki", external_id="1")])
    tg = FakeSource(
        "telegram",
        [
            make_listing("Айфон 13 128гб", source="telegram", external_id="2"),
            make_listing("Чехол iPhone 13", source="telegram", external_id="3"),  # accessory
        ],
    )
    outcome = await orchestrator(baz, tg).search(QUERY, City.LIMASSOL)

    assert {li.external_id for li in outcome.listings} == {"1", "2"}
    by_name = {s.name: s for s in outcome.statuses}
    assert (by_name["bazaraki"].count, by_name["bazaraki"].fetched) == (1, 1)
    assert (by_name["telegram"].count, by_name["telegram"].fetched) == (1, 2)
    assert all(s.ok for s in outcome.statuses)
    assert not outcome.failed_sources
    assert not outcome.all_failed


async def test_a_failing_source_yields_partial_results_and_a_note() -> None:
    good = FakeSource("bazaraki", [make_listing("iPhone 13", external_id="1")])
    bad = FakeSource("telegram", SourceError("db down"))
    outcome = await orchestrator(good, bad).search(QUERY, City.ALL_CYPRUS)

    assert [li.external_id for li in outcome.listings] == ["1"]
    assert [s.name for s in outcome.failed_sources] == ["telegram"]
    assert "db down" in (outcome.failed_sources[0].error or "")
    assert not outcome.all_failed


async def test_unexpected_exceptions_are_contained_too() -> None:
    outcome = await orchestrator(
        FakeSource("a", RuntimeError("kaboom")), FakeSource("b", [make_listing(external_id="1")])
    ).search(QUERY, City.ALL_CYPRUS)
    assert [s.ok for s in outcome.statuses] == [False, True]


async def test_a_slow_source_times_out_without_delaying_the_others() -> None:
    fast = FakeSource("fast", [make_listing("iPhone 13", external_id="1")])
    slow = FakeSource("slow", [make_listing("iPhone 13", external_id="2")], delay=5)
    outcome = await orchestrator(fast, slow, timeout=0.05).search(QUERY, City.ALL_CYPRUS)

    assert [li.external_id for li in outcome.listings] == ["1"]
    slow_status = next(s for s in outcome.statuses if s.name == "slow")
    assert not slow_status.ok
    assert "timed out" in (slow_status.error or "")


async def test_all_sources_failing_is_reported() -> None:
    outcome = await orchestrator(FakeSource("a", SourceError("x"))).search(QUERY, City.ALL_CYPRUS)
    assert outcome.all_failed
    assert outcome.listings == []


async def test_no_sources_is_an_empty_but_not_failed_outcome() -> None:
    outcome = await orchestrator().search(QUERY, City.ALL_CYPRUS)
    assert outcome.listings == []
    assert not outcome.all_failed


async def test_city_scoping_includes_unknown_only_for_all_cyprus() -> None:
    found = [
        make_listing("iPhone 13", external_id="lim", city=City.LIMASSOL),
        make_listing("iPhone 13", external_id="pap", city=City.PAPHOS),
        make_listing("iPhone 13", external_id="unk", city=City.UNKNOWN),
    ]
    in_limassol = await orchestrator(FakeSource("s", found)).search(QUERY, City.LIMASSOL)
    everywhere = await orchestrator(FakeSource("s", found)).search(QUERY, City.ALL_CYPRUS)

    assert [li.external_id for li in in_limassol.listings] == ["lim"]
    assert {li.external_id for li in everywhere.listings} == {"lim", "pap", "unk"}


async def test_duplicates_by_source_and_id_are_merged() -> None:
    dup = make_listing("iPhone 13", source="telegram", external_id="7")
    outcome = await orchestrator(FakeSource("telegram", [dup, dup])).search(QUERY, City.ALL_CYPRUS)
    assert len(outcome.listings) == 1


async def test_sources_receive_the_query_city_and_default_filters() -> None:
    source = FakeSource("s")
    await orchestrator(source).search(QUERY, City.PAPHOS)
    query, city, filters = source.calls[0]
    assert (query, city, filters) == (QUERY, City.PAPHOS, Filters())


async def test_progress_is_reported_per_source_and_callback_errors_are_ignored() -> None:
    seen: list[SourceStatus] = []

    async def on_progress(status: SourceStatus) -> None:
        seen.append(status)
        raise RuntimeError("telegram edit failed")

    outcome = await orchestrator(
        FakeSource("a", [make_listing(external_id="1")]), FakeSource("b", SourceError("x"))
    ).search(QUERY, City.ALL_CYPRUS, on_progress)

    assert sorted(s.name for s in seen) == ["a", "b"]
    assert len(outcome.statuses) == 2


async def test_facebook_stub_is_a_valid_source_that_fails_gracefully() -> None:
    stub = FacebookMarketplaceSource()
    assert isinstance(stub, ListingSource)
    outcome = await orchestrator(stub).search(QUERY, City.ALL_CYPRUS)
    assert outcome.all_failed
    assert "NotImplementedError" in (outcome.statuses[0].error or "")
