"""Search use-case: validate -> expand -> fan out -> log. The only thing handlers call to search."""

from __future__ import annotations

from typing import Protocol

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aggregator.db.models import SearchLog
from aggregator.domain.cities import City
from aggregator.domain.models import ExpandedQuery, Filters
from aggregator.query.normalize import normalize_input
from aggregator.search.filters import build_view
from aggregator.search.models import ResultView, SearchOutcome
from aggregator.search.orchestrator import ProgressCallback, SearchOrchestrator
from aggregator.services.users import UserProfile

log = structlog.get_logger()


class InvalidQueryError(ValueError):
    """The user's text cannot be searched. `reason` is an i18n-friendly code."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason  # "empty" | "too_long" | "no_content"


class Expander(Protocol):
    async def expand(self, text: str) -> ExpandedQuery: ...


class SearchLogStore(Protocol):
    async def add(
        self, user_id: int | None, query: str, city: str, result_count: int, duration_ms: int
    ) -> None: ...


class DbSearchLogStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def add(
        self, user_id: int | None, query: str, city: str, result_count: int, duration_ms: int
    ) -> None:
        async with self._session_factory() as session, session.begin():
            session.add(
                SearchLog(
                    user_id=user_id or None,
                    query=query,
                    city=city,
                    result_count=result_count,
                    duration_ms=duration_ms,
                )
            )


class SearchService:
    def __init__(
        self,
        expander: Expander,
        orchestrator: SearchOrchestrator,
        search_log: SearchLogStore | None = None,
        *,
        best_deal_ratio: float = 0.75,
        max_query_length: int = 100,
    ) -> None:
        self._expander = expander
        self._orchestrator = orchestrator
        self._log = search_log
        self._best_deal_ratio = best_deal_ratio
        self._max_query_length = max_query_length

    @property
    def max_query_length(self) -> int:
        return self._max_query_length

    def validate_query(self, text: str) -> str:
        cleaned = " ".join(text.split())
        if not cleaned:
            raise InvalidQueryError("empty")
        if len(cleaned) > self._max_query_length:
            raise InvalidQueryError("too_long")
        if not normalize_input(cleaned):
            raise InvalidQueryError("no_content")  # e.g. only emoji / punctuation
        return cleaned

    async def search(
        self,
        user: UserProfile,
        text: str,
        on_progress: ProgressCallback | None = None,
    ) -> SearchOutcome:
        cleaned = self.validate_query(text)
        city = user.city or City.ALL_CYPRUS
        query = await self._expander.expand(cleaned)
        outcome = await self._orchestrator.search(query, city, on_progress)
        await self._record(user, cleaned, outcome)
        return outcome

    def view(self, outcome: SearchOutcome, filters: Filters) -> ResultView:
        return build_view(outcome.listings, filters, self._best_deal_ratio)

    async def _record(self, user: UserProfile, text: str, outcome: SearchOutcome) -> None:
        log.info(
            "search.done",
            city=outcome.city.value,
            results=len(outcome.listings),
            duration_ms=outcome.duration_ms,
            failed=[s.name for s in outcome.failed_sources],
        )
        if self._log is None:
            return
        try:
            await self._log.add(
                user.id or None,
                text,
                outcome.city.value,
                len(outcome.listings),
                outcome.duration_ms,
            )
        except Exception:  # analytics must never break a search
            log.warning("search.log_failed", exc_info=True)
