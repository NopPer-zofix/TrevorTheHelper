from __future__ import annotations

from decimal import Decimal

import pytest

from aggregator.domain.models import Filters, SortOrder
from aggregator.services.filters import (
    FilterError,
    parse_price_input,
    set_price_bound,
    set_sort,
    set_source,
)

D = Decimal


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("150", D(150)),
        ("  150  ", D(150)),
        ("€150", D(150)),
        ("150€", D(150)),
        ("150 EUR", D(150)),
        ("150 евро", D(150)),
        ("1 500", D(1500)),
        ("1,500", D(1500)),
        ("1.500,50", D("1500.50")),
        ("99,5", D("99.5")),
        ("0", D(0)),
        ("0.00", D(0)),
        ("€ 0", D(0)),
    ],
)
def test_parse_price_input_accepts_bare_amounts(text: str, expected: Decimal) -> None:
    assert parse_price_input(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "iphone 13",  # a new search, not a price
        "13 pro",
        "bike under 200",
        "-5",
        "abc",
        "",
        "€",
        "99999999999",  # absurd
        "150 usd",  # only euros are accepted
    ],
)
def test_parse_price_input_rejects_everything_else(text: str) -> None:
    assert parse_price_input(text) is None


def test_set_price_bound_sets_and_clears() -> None:
    f = set_price_bound(Filters(), "min", D(100))
    f = set_price_bound(f, "max", D(300))
    assert (f.min_price, f.max_price) == (D(100), D(300))
    assert set_price_bound(f, "min", D(0)).min_price is None
    assert set_price_bound(f, "max", D(0)).max_price is None


def test_price_bounds_can_never_cross() -> None:
    f = Filters(min_price=D(100), max_price=D(300))
    with pytest.raises(FilterError) as low:
        set_price_bound(f, "min", D(301))
    assert low.value.reason == "range"
    with pytest.raises(FilterError):
        set_price_bound(f, "max", D(99))
    # equal bounds are fine, and a bound is unconstrained while the other side is unset
    assert set_price_bound(f, "min", D(300)).min_price == D(300)
    assert set_price_bound(Filters(), "max", D(5)).max_price == D(5)


def test_set_sort_and_source_validate_their_input() -> None:
    assert set_sort(Filters(), "cheapest").sort is SortOrder.CHEAPEST
    with pytest.raises(FilterError):
        set_sort(Filters(), "random")

    sources = ["bazaraki", "telegram"]
    assert set_source(Filters(), "telegram", sources).source == "telegram"
    assert set_source(Filters(source="telegram"), None, sources).source is None
    with pytest.raises(FilterError):
        set_source(Filters(), "facebook", sources)  # not enabled


def test_changes_do_not_mutate_the_original() -> None:
    original = Filters()
    set_price_bound(original, "min", D(5))
    set_sort(original, "cheapest")
    assert original == Filters()
