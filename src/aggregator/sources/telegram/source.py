"""Telegram groups as a `ListingSource`. Reads what the indexer stored; never talks to Telegram."""

from __future__ import annotations

from aggregator.db.repositories import ListingRepository
from aggregator.domain.cities import City
from aggregator.domain.models import ExpandedQuery, Filters, Listing
from aggregator.sources.base import SourceError, search_terms

SOURCE_NAME = "telegram"


class TelegramSource:
    name = SOURCE_NAME

    def __init__(
        self,
        repository: ListingRepository,
        *,
        max_age_days: int = 30,
        max_terms: int = 6,
    ) -> None:
        self._repository = repository
        self._max_age_days = max_age_days
        self._max_terms = max_terms

    async def search(
        self, query: ExpandedQuery, city: City | None, filters: Filters
    ) -> list[Listing]:
        # `filters` are applied by the orchestrator on the merged result set.
        terms = search_terms(query, self._max_terms)
        if not terms:
            return []
        try:
            return await self._repository.search(
                SOURCE_NAME, terms, city, max_age_days=self._max_age_days
            )
        except Exception as exc:  # DB down, bad SQL...: degrade to partial results upstream
            raise SourceError(f"telegram index query failed: {exc}") from exc
