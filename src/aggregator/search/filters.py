"""Apply the user's filters/sort to an already-fetched result set (no re-fetching)."""

from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from aggregator.analytics.price_cases import PriceCase, PriceCuts, find_price_cuts
from aggregator.analytics.stats import compute_stats, find_best_deals
from aggregator.domain.models import Filters, Listing, SortOrder
from aggregator.search.models import ResultView, UnusualPrices

_NO_PRICE_LAST = Decimal("Infinity")


def _passes(listing: Listing, filters: Filters) -> bool:
    if filters.source is not None and listing.source != filters.source:
        return False
    if filters.area is not None and listing.area != filters.area:
        return False
    if filters.min_price is None and filters.max_price is None:
        return True
    price = listing.price_eur
    if price is None:  # an unpriced listing cannot satisfy a price bound
        return False
    if filters.min_price is not None and price < filters.min_price:
        return False
    return not (filters.max_price is not None and price > filters.max_price)


def _newest_key(listing: Listing) -> datetime:
    return listing.posted_at


def sort_listings(listings: Sequence[Listing], order: SortOrder) -> list[Listing]:
    """Unpriced listings always go last for price-based orders; ties are broken by recency."""
    by_newest = sorted(listings, key=_newest_key, reverse=True)  # stable base order
    if order is SortOrder.NEWEST:
        return by_newest
    if order is SortOrder.CHEAPEST:
        return sorted(by_newest, key=lambda li: li.price_eur or _NO_PRICE_LAST)

    # BEST_DEAL: lowest price relative to the median of the set (largest discount first).
    prices = [p for li in listings if (p := li.price_eur) is not None]
    if not prices:
        return by_newest
    median = Decimal(str(statistics.median(float(p) for p in prices)))
    if median <= 0:
        return by_newest
    return sorted(by_newest, key=lambda li: (li.price_eur or _NO_PRICE_LAST) / median)


def apply_filters(listings: Sequence[Listing], filters: Filters) -> list[Listing]:
    return sort_listings([li for li in listings if _passes(li, filters)], filters.sort)


_SINGLE_CLASS_SHARE = 0.85  # one top-level category must hold this share to count as one product
_MIN_CATEGORISED = 6


def _spans_several_categories(listings: Sequence[Listing]) -> bool:
    """True when the results are a real mix of kinds (rentals and sales, phones and bikes).

    The price cases assume one kind of product, so for such a set a "far from the others" price
    says nothing: the minority group is just another kind. A stray ad or two does not count.
    """
    tops = Counter(li.category.split("/")[0] for li in listings if li.category)
    total = sum(tops.values())
    return total >= _MIN_CATEGORISED and max(tops.values()) / total < _SINGLE_CLASS_SHARE


def build_view(
    listings: Sequence[Listing], filters: Filters, best_deal_ratio: float = 0.75
) -> ResultView:
    """Filtered + sorted listings with stats and best deals computed for exactly that subset.

    Unusually priced listings (far from the main price group of the *whole* result set, so the
    boundaries do not move when the user narrows the price range) are hidden unless the user asked
    to see them, and are always left out of the statistics and the best deals.
    """
    if _spans_several_categories(listings):
        cuts = PriceCuts(mixed=True)  # rentals next to sales: no price is "unusual" for the set
    else:
        cuts = find_price_cuts([p for li in listings if (p := li.price_eur) is not None])
    # The area picker lists the areas of what the user would see if no area were chosen, so its
    # counts always match what a tap will show.
    without_area = filters.model_copy(update={"area": None})
    candidates = [li for li in listings if _passes(li, without_area)]
    pool = [
        li
        for li in candidates
        if filters.show_unusual_prices or cuts.case_of(li.price_eur) is PriceCase.NORMAL
    ]
    area_counts = Counter(li.area for li in pool if li.area)
    areas = sorted(area_counts.items(), key=lambda item: (-item[1], item[0]))
    passing = [li for li in candidates if filters.area is None or li.area == filters.area]

    normal: list[Listing] = []
    unusual: list[Listing] = []
    low = high = 0
    for listing in passing:
        case = cuts.case_of(listing.price_eur)
        if case is PriceCase.NORMAL:
            normal.append(listing)
            continue
        unusual.append(listing)
        if case is PriceCase.LOW:
            low += 1
        else:
            high += 1

    shown = [*normal, *unusual] if filters.show_unusual_prices else normal
    selected = sort_listings(shown, filters.sort)
    return ResultView(
        listings=selected,
        stats=compute_stats([li.price_eur for li in normal]),
        best_deals=find_best_deals(normal, ratio=best_deal_ratio),
        unpriced_count=sum(1 for li in selected if li.price_eur is None),
        counts_by_source=dict(Counter(li.source for li in selected)),
        unusual=UnusualPrices(
            low_count=low,
            high_count=high,
            low_below=cuts.low_below,
            high_above=cuts.high_above,
            mixed=cuts.mixed,
        ),
        unusual_keys=frozenset(li.key for li in unusual),
        areas=areas,
    )
