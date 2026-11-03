"""Bazaraki as a `ListingSource`: live fetch per request, short-TTL cache per (term, city)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import structlog

from aggregator.cache import Cache
from aggregator.domain.cities import City
from aggregator.domain.models import ExpandedQuery, Filters, Listing
from aggregator.sources.base import SourceError
from aggregator.sources.bazaraki.client import BazarakiClient
from aggregator.sources.bazaraki.parser import SOURCE_NAME, parse_search_page
from aggregator.sources.bazaraki.selectors import search_path

log = structlog.get_logger()


def search_terms(query: ExpandedQuery, max_terms: int) -> list[str]:
    """Primary term first, then variants; case-insensitive dedupe; capped to stay polite."""
    seen: set[str] = set()
    terms: list[str] = []
    for candidate in [query.normalized, *query.variants]:
        cleaned = " ".join(candidate.split())
        if cleaned and cleaned.lower() not in seen:
            seen.add(cleaned.lower())
            terms.append(cleaned)
    return terms[: max(max_terms, 1)]


class BazarakiSource:
    name = SOURCE_NAME

    def __init__(
        self,
        client: BazarakiClient,
        cache: Cache[list[Listing]],
        *,
        cache_ttl_seconds: float = 300,
        max_pages: int = 3,
        max_terms: int = 2,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._client = client
        self._cache = cache
        self._ttl = cache_ttl_seconds
        self._max_pages = max_pages
        self._max_terms = max_terms
        self._now = now

    async def search(
        self, query: ExpandedQuery, city: City | None, filters: Filters
    ) -> list[Listing]:
        # `filters` are applied by the orchestrator on the merged result set.
        scope = city if city not in (None, City.ALL_CYPRUS) else None
        merged: dict[str, Listing] = {}
        terms = search_terms(query, self._max_terms)
        for index, term in enumerate(terms):
            try:
                found = await self._search_term(term, scope)
            except SourceError:
                if index == 0 or not merged:
                    raise
                log.warning("bazaraki.term_failed", term=term)
                continue
            for listing in found:
                merged.setdefault(listing.external_id, listing)
        return list(merged.values())

    async def _search_term(self, term: str, scope: City | None) -> list[Listing]:
        key = f"{SOURCE_NAME}:{scope.value if scope else 'all'}:{term.lower()}"
        cached = await self._cache.get(key)
        if cached is not None:
            return cached

        listings: list[Listing] = []
        for page in range(1, self._max_pages + 1):
            params: dict[str, str | int] = {"q": term}
            if page > 1:
                params["page"] = page
            html = await self._client.get_html(search_path(scope.value if scope else None), params)
            parsed = parse_search_page(html, now=self._now(), page=page, searched_city=scope)
            listings.extend(parsed.listings)
            if not parsed.listings or not parsed.has_next_page:
                break

        await self._cache.set(key, listings, self._ttl)
        return listings
