"""Shared builders for tests (imported as `from factories import ...`)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from aggregator.domain.cities import City
from aggregator.domain.models import Listing

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


def make_listing(
    title: str = "iPhone 13 128GB",
    *,
    price: str | int | None = 500,
    currency: str | None = "EUR",
    source: str = "bazaraki",
    external_id: str | None = None,
    city: City = City.LIMASSOL,
    description: str | None = None,
    days_old: int = 1,
) -> Listing:
    ext = external_id or f"{source}-{abs(hash((title, price, source, days_old))) % 10**8}"
    return Listing(
        source=source,
        external_id=ext,
        url=f"https://example.test/{source}/{ext}",
        title=title,
        description=description,
        price_amount=Decimal(str(price)) if price is not None else None,
        currency=currency,
        city=city,
        posted_at=NOW - timedelta(days=days_old),
    )
