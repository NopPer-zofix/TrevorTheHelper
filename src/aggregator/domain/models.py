"""Core domain models shared by sources, search, analytics and the bot."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from aggregator.domain.cities import City
from aggregator.domain.currency import CurrencyConverter

_converter = CurrencyConverter()


class Listing(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: str
    external_id: str
    url: str
    title: str
    description: str | None = None
    price_amount: Decimal | None = None  # None = missing / "negotiable"
    currency: str | None = None
    city: City = City.UNKNOWN
    posted_at: datetime
    # Source category path, reduced to the catalog (e.g. "telephones/mobile-phones"). None when the
    # source has no categories (Telegram posts) or the advert's category is unknown.
    category: str | None = None

    @property
    def price_eur(self) -> Decimal | None:
        return _converter.to_eur(self.price_amount, self.currency)

    @property
    def key(self) -> tuple[str, str]:
        return (self.source, self.external_id)


class SearchQuery(BaseModel):
    text: str
    city: City = City.ALL_CYPRUS
    language: str = "en"


class ExpandedQuery(BaseModel):
    """Structured form of a free-text query (produced by the LLM or the rule-based fallback)."""

    original: str
    normalized: str
    brand: str | None = None
    model: str | None = None
    specs: list[str] = Field(default_factory=list)
    variants: list[str] = Field(default_factory=list)  # EN + RU search-term variants
    negative_terms: list[str] = Field(default_factory=list)
    category_hint: str | None = None


class SortOrder(StrEnum):
    CHEAPEST = "cheapest"
    NEWEST = "newest"
    BEST_DEAL = "best_deal"


class Filters(BaseModel):
    min_price: Decimal | None = None  # EUR
    max_price: Decimal | None = None  # EUR
    sort: SortOrder = SortOrder.NEWEST
    source: str | None = None  # None = all sources
    # Listings priced far outside the main group (see analytics/price_cases.py) are hidden unless
    # this is True. They never count towards the statistics either way.
    show_unusual_prices: bool = False
    # A source-side category scope ("real-estate-to-rent/apartments-flats"). It is set by the
    # search itself when the user answers a category question, never by the Filters menu, and only
    # sources (and the orchestrator's safety check) look at it. It is not a "user filter".
    category: str | None = None

    @property
    def is_default(self) -> bool:
        return self.model_copy(update={"category": None}) == Filters()


class PriceStats(BaseModel):
    priced_count: int  # listings with a usable price, before outlier removal
    sample_size: int  # listings left after IQR outlier removal
    outliers_removed: int
    average: Decimal | None = None
    median: Decimal | None = None
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    reliable: bool = False  # False when the sample is too small to trust


class BestDeal(BaseModel):
    listing: Listing
    discount_pct: int  # versus the median, e.g. 30 = 30% below
