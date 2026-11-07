"""Changing the user's result filters. Pure functions: handlers parse input, call these, render."""

from __future__ import annotations

import re
from collections.abc import Sequence
from decimal import Decimal
from typing import Literal

from aggregator.domain.models import Filters, SortOrder
from aggregator.domain.pricing import parse_price

PriceField = Literal["min", "max"]
MAX_PRICE = Decimal("10000000")

# A bare amount, optionally with a euro marker: "150", "€150", "1 500", "1,500.50", "150 евро".
_PRICE_INPUT = re.compile(
    r"^[€\s]*(?P<num>\d[\d\s.,]*?)\s*(?:€|eur|euros?|евро)?\.?\s*$", re.IGNORECASE
)


class FilterError(ValueError):
    """A filter change that is not allowed. `reason`: "range" | "unknown_source"."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def parse_price_input(text: str) -> Decimal | None:
    """Strict: the whole message must be a number. Returns Decimal(0) for "0" (= clear the
    bound), None when the text is not a price (the caller then treats it as a new search)."""
    match = _PRICE_INPUT.match(text)
    if match is None:
        return None
    number = match.group("num").strip()
    if re.fullmatch(r"[0.,\s]+", number):  # starts with a digit: this is "0" / "0.00"
        return Decimal(0)
    value = parse_price(number)
    if value is None or value > MAX_PRICE:
        return None
    return value


def set_price_bound(filters: Filters, field: PriceField, value: Decimal) -> Filters:
    """Set (or, with 0, clear) the min/max price. The bounds may never cross."""
    bound = None if value == 0 else value
    if field == "min":
        if bound is not None and filters.max_price is not None and bound > filters.max_price:
            raise FilterError("range")
        return filters.model_copy(update={"min_price": bound})
    if bound is not None and filters.min_price is not None and bound < filters.min_price:
        raise FilterError("range")
    return filters.model_copy(update={"max_price": bound})


def set_sort(filters: Filters, order: str) -> Filters:
    try:
        return filters.model_copy(update={"sort": SortOrder(order)})
    except ValueError as exc:
        raise FilterError("unknown_sort") from exc


def set_source(filters: Filters, source: str | None, available: Sequence[str]) -> Filters:
    """`source=None` means all sources. Only sources that are actually enabled are accepted."""
    if source is not None and source not in available:
        raise FilterError("unknown_source")
    return filters.model_copy(update={"source": source})


def toggle_unusual_prices(filters: Filters) -> Filters:
    """Show / hide the listings whose price is far outside the main group."""
    return filters.model_copy(update={"show_unusual_prices": not filters.show_unusual_prices})
