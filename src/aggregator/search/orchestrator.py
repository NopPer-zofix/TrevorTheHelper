"""Fan a query out to every source concurrently, tolerate failures, merge and clean the results."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence

import structlog

from aggregator.domain.cities import City, city_matches
from aggregator.domain.models import ExpandedQuery, Filters, Listing
from aggregator.search.models import SearchOutcome, SourceStatus
from aggregator.search.relevance import DEFAULT_MIN_SCORE, filter_relevant
from aggregator.sources.base import ListingSource

log = structlog.get_logger()

ProgressCallback = Callable[[SourceStatus], Awaitable[None]]
_MAX_ERROR_CHARS = 200


class SearchOrchestrator:
    """Works with any number of sources; one failing or slow source yields partial results."""

    def __init__(
        self,
        sources: Sequence[ListingSource],
        *,
        source_timeout_seconds: float = 12.0,
        min_relevance: float = DEFAULT_MIN_SCORE,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._sources = list(sources)
        self._timeout = source_timeout_seconds
        self._min_relevance = min_relevance
        self._clock = clock

    @property
    def source_names(self) -> list[str]:
        return [source.name for source in self._sources]

    async def search(
        self,
        query: ExpandedQuery,
        city: City,
        on_progress: ProgressCallback | None = None,
    ) -> SearchOutcome:
        started = self._clock()
        results = await asyncio.gather(
            *(self._run_source(source, query, city, on_progress) for source in self._sources)
        )

        merged: dict[tuple[str, str], Listing] = {}
        for _, listings in results:
            for listing in listings:
                merged.setdefault(listing.key, listing)

        return SearchOutcome(
            query=query,
            city=city,
            listings=list(merged.values()),
            statuses=[status for status, _ in results],
            duration_ms=self._elapsed_ms(started),
        )

    async def _run_source(
        self,
        source: ListingSource,
        query: ExpandedQuery,
        city: City,
        on_progress: ProgressCallback | None,
    ) -> tuple[SourceStatus, list[Listing]]:
        started = self._clock()
        listings: list[Listing] = []
        try:
            # Sources get default filters: the user's filters are applied afterwards on the
            # merged set so they can change without re-fetching.
            fetched = await asyncio.wait_for(
                source.search(query, city, Filters()), timeout=self._timeout
            )
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            status = SourceStatus(
                name=source.name,
                ok=False,
                error=f"timed out after {self._timeout:g}s",
                duration_ms=self._elapsed_ms(started),
            )
            log.warning("search.source_timeout", source=source.name)
        except Exception as exc:  # one broken source must never break the search
            status = SourceStatus(
                name=source.name,
                ok=False,
                error=f"{type(exc).__name__}: {exc}"[:_MAX_ERROR_CHARS],
                duration_ms=self._elapsed_ms(started),
            )
            log.warning("search.source_failed", source=source.name, error=status.error)
        else:
            in_city = [li for li in fetched if city_matches(li.city, city)]
            listings = filter_relevant(in_city, query, self._min_relevance)
            status = SourceStatus(
                name=source.name,
                ok=True,
                count=len(listings),
                fetched=len(fetched),
                duration_ms=self._elapsed_ms(started),
            )

        if on_progress is not None:
            try:
                await on_progress(status)
            except Exception:  # a UI hiccup (e.g. Telegram edit error) must not fail the search
                log.warning("search.progress_callback_failed", exc_info=True)
        return status, listings

    def _elapsed_ms(self, started: float) -> int:
        return int((self._clock() - started) * 1000)
