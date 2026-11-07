"""Search use-case: validate -> expand -> fan out -> log. The only thing handlers call to search."""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aggregator.db.models import SearchLog
from aggregator.domain.cities import City
from aggregator.domain.models import ExpandedQuery, Filters
from aggregator.query.normalize import normalize_input
from aggregator.search.category_choice import Decision, Intent, Resolved, decide, intent_of
from aggregator.search.filters import build_view
from aggregator.search.models import ResultView, SearchOutcome
from aggregator.search.orchestrator import ProgressCallback, SearchOrchestrator
from aggregator.services.users import UserProfile
from aggregator.sources.base import CategoryExplorer

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


@dataclass(frozen=True)
class CategoryPlan:
    """What to do about categories before searching: the expanded query, the category sample it
    was based on, and the decision (ask a question, or search in a category / everywhere)."""

    text: str
    query: ExpandedQuery
    counts: Mapping[str, int]
    intent: Intent | None
    decision: Decision


class SearchService:
    def __init__(
        self,
        expander: Expander,
        orchestrator: SearchOrchestrator,
        search_log: SearchLogStore | None = None,
        *,
        best_deal_ratio: float = 0.75,
        max_query_length: int = 100,
        explorers: Sequence[CategoryExplorer] = (),
        explore_timeout_seconds: float = 10.0,
    ) -> None:
        self._expander = expander
        self._orchestrator = orchestrator
        self._log = search_log
        self._best_deal_ratio = best_deal_ratio
        self._max_query_length = max_query_length
        self._explorers = list(explorers)
        self._explore_timeout = explore_timeout_seconds

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

    async def plan_category(self, user: UserProfile, text: str) -> CategoryPlan:
        """Look at where the results fall and decide whether a category question is needed.

        Never raises for a valid query: a source that cannot be explored just contributes nothing,
        and with no evidence the plan is "search everywhere" (the behaviour before categories).
        """
        cleaned = self.validate_query(text)
        query = await self._expander.expand(cleaned)
        counts = await self._explore(query, user.city or City.ALL_CYPRUS)
        intent = intent_of(cleaned)
        decision: Decision = decide(counts, None, intent) if counts else Resolved(None)
        return CategoryPlan(cleaned, query, counts, intent, decision)

    def next_category_step(
        self, counts: Mapping[str, int], chosen: str, intent: Intent | None
    ) -> Decision:
        """The decision after the user picked `chosen` (a path settled so far)."""
        return decide(counts, chosen, intent)

    async def _explore(self, query: ExpandedQuery, city: City) -> dict[str, int]:
        async def one(explorer: CategoryExplorer) -> dict[str, int]:
            try:
                return await asyncio.wait_for(
                    explorer.explore_categories(query, city), timeout=self._explore_timeout
                )
            except Exception:  # an exploration failure only means "no category question"
                log.warning("search.explore_failed", source=explorer.name, exc_info=True)
                return {}

        total: Counter[str] = Counter()
        for counts in await asyncio.gather(*(one(e) for e in self._explorers)):
            total.update(counts)
        return dict(total)

    async def search(
        self,
        user: UserProfile,
        text: str,
        on_progress: ProgressCallback | None = None,
        *,
        category: str | None = None,
        query: ExpandedQuery | None = None,
    ) -> SearchOutcome:
        cleaned = self.validate_query(text)
        city = user.city or City.ALL_CYPRUS
        expanded = query if query is not None else await self._expander.expand(cleaned)
        outcome = await self._orchestrator.search(expanded, city, on_progress, category)
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
