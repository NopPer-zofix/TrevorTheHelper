from __future__ import annotations

from decimal import Decimal

from aggregator.domain.models import Filters, SortOrder
from aggregator.search.filters import apply_filters, build_view, sort_listings
from factories import make_listing

D = Decimal


def listings() -> list:
    return [
        make_listing("a", price=100, source="bazaraki", external_id="a", days_old=3),
        make_listing("b", price=300, source="telegram", external_id="b", days_old=1),
        make_listing("c", price=None, source="telegram", external_id="c", days_old=0),
        make_listing("d", price=200, source="bazaraki", external_id="d", days_old=2),
        make_listing("e", price=80, currency="GBP", source="telegram", external_id="e", days_old=5),
    ]


def ids(items: list) -> list[str]:
    return [li.external_id for li in items]


def test_default_filters_sort_newest_first() -> None:
    assert ids(apply_filters(listings(), Filters())) == ["c", "b", "d", "a", "e"]


def test_cheapest_puts_unpriced_last_and_converts_currency() -> None:
    result = apply_filters(listings(), Filters(sort=SortOrder.CHEAPEST))
    assert ids(result)[-1] == "c"
    assert set(ids(result)[:4]) == {"a", "b", "d", "e"}
    # 80 GBP is ~93 EUR, so it must sort below the 100 EUR listing
    assert ids(result)[:2] == ["e", "a"]


def test_price_bounds_are_in_eur_and_exclude_unpriced() -> None:
    result = apply_filters(listings(), Filters(min_price=D(100), max_price=D(250)))
    assert set(ids(result)) == {"a", "d"}


def test_only_a_max_price_also_excludes_unpriced() -> None:
    assert "c" not in ids(apply_filters(listings(), Filters(max_price=D(1000))))


def test_source_filter() -> None:
    assert set(ids(apply_filters(listings(), Filters(source="bazaraki")))) == {"a", "d"}


def test_best_deal_sort_orders_by_price_relative_to_median() -> None:
    result = sort_listings(listings(), SortOrder.BEST_DEAL)
    assert ids(result)[0] == "e"
    assert ids(result)[-1] == "c"


def test_best_deal_sort_without_prices_falls_back_to_newest() -> None:
    items = [
        make_listing("x", price=None, external_id="x", days_old=2),
        make_listing("y", price=None, external_id="y", days_old=1),
    ]
    assert ids(sort_listings(items, SortOrder.BEST_DEAL)) == ["y", "x"]


def test_build_view_stats_and_counts_reflect_the_filtered_subset() -> None:
    view = build_view(listings(), Filters(source="telegram"))
    assert view.counts_by_source == {"telegram": 3}
    assert view.unpriced_count == 1
    assert view.stats.priced_count == 2
    assert view.stats.reliable is False
    assert view.best_deals == []


def test_build_view_finds_best_deals_when_enough_priced_listings() -> None:
    items = [
        make_listing(f"i{n}", price=p, external_id=str(n))
        for n, p in enumerate([400, 410, 420, 430, 440, 250])
    ]
    view = build_view(items, Filters())
    assert [d.listing.external_id for d in view.best_deals] == ["5"]
    assert view.best_deals[0].discount_pct > 30
