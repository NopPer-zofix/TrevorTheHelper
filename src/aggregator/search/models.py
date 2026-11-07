"""Result types produced by the orchestrator and consumed by the service layer and the bot."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

from aggregator.domain.cities import City
from aggregator.domain.models import BestDeal, ExpandedQuery, Listing, PriceStats


class SourceStatus(BaseModel):
    """What happened when one source was queried."""

    name: str
    ok: bool
    count: int = 0  # relevant listings this source contributed
    fetched: int = 0  # listings returned before the relevance filter
    error: str | None = None
    duration_ms: int = 0


class SearchOutcome(BaseModel):
    """The fetched, de-duplicated and relevance-filtered result set. Filters are NOT applied
    here: the user can change them afterwards without re-fetching."""

    query: ExpandedQuery
    city: City
    listings: list[Listing] = Field(default_factory=list)
    statuses: list[SourceStatus] = Field(default_factory=list)
    duration_ms: int = 0

    @property
    def failed_sources(self) -> list[SourceStatus]:
        return [s for s in self.statuses if not s.ok]

    @property
    def all_failed(self) -> bool:
        return bool(self.statuses) and not any(s.ok for s in self.statuses)


class UnusualPrices(BaseModel):
    """Listings whose price is far from the main group (see analytics/price_cases.py)."""

    low_count: int = 0  # among the listings that pass the user's other filters
    high_count: int = 0
    low_below: Decimal | None = None
    high_above: Decimal | None = None
    mixed: bool = False  # no dominant price group: nothing was flagged

    @property
    def count(self) -> int:
        return self.low_count + self.high_count


class ResultView(BaseModel):
    """`SearchOutcome` with the user's filters applied, plus stats and deals for that subset."""

    listings: list[Listing]  # filtered and sorted
    stats: PriceStats
    best_deals: list[BestDeal]
    unpriced_count: int
    counts_by_source: dict[str, int]  # after filters
    unusual: UnusualPrices = Field(default_factory=UnusualPrices)
    # Listings flagged as unusually priced (hidden, or shown with a marker when the user asks).
    unusual_keys: frozenset[tuple[str, str]] = frozenset()
