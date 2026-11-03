"""Price statistics with IQR outlier removal, and best-deal detection."""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from decimal import Decimal

from aggregator.domain.models import BestDeal, Listing, PriceStats

MIN_RELIABLE_SAMPLE = 3
MIN_LISTINGS_FOR_BEST_DEALS = 5
MIN_SAMPLE_FOR_IQR = 4
IQR_FACTOR = 1.5
MAX_BEST_DEALS = 3
MIN_DEAL_PRICE_RATIO = 0.2


def _q(value: float) -> Decimal:
    return Decimal(str(round(value, 2)))


def remove_outliers(prices: Sequence[Decimal]) -> list[Decimal]:
    """Drop prices outside [Q1 - 1.5*IQR, Q3 + 1.5*IQR]. Too few points -> returned unchanged."""
    if len(prices) < MIN_SAMPLE_FOR_IQR:
        return list(prices)
    floats = [float(p) for p in prices]
    q1, _, q3 = statistics.quantiles(floats, n=4, method="inclusive")
    iqr = q3 - q1
    low, high = q1 - IQR_FACTOR * iqr, q3 + IQR_FACTOR * iqr
    return [p for p, f in zip(prices, floats, strict=True) if low <= f <= high]


def compute_stats(prices_eur: Sequence[Decimal | None]) -> PriceStats:
    """Average / median / min / max over priced listings, after IQR outlier removal."""
    priced = [p for p in prices_eur if p is not None]
    sample = remove_outliers(priced)
    if not sample:
        return PriceStats(priced_count=0, sample_size=0, outliers_removed=0)
    floats = [float(p) for p in sample]
    return PriceStats(
        priced_count=len(priced),
        sample_size=len(sample),
        outliers_removed=len(priced) - len(sample),
        average=_q(statistics.fmean(floats)),
        median=_q(statistics.median(floats)),
        minimum=min(sample),
        maximum=max(sample),
        reliable=len(sample) >= MIN_RELIABLE_SAMPLE,
    )


def listing_stats(listings: Sequence[Listing]) -> PriceStats:
    return compute_stats([listing.price_eur for listing in listings])


def find_best_deals(
    listings: Sequence[Listing],
    ratio: float = 0.75,
    limit: int = MAX_BEST_DEALS,
) -> list[BestDeal]:
    """Listings priced at or below `ratio` x median, biggest discount first.

    Needs at least 5 priced listings. The median comes from the outlier-filtered sample.
    Candidates below `MIN_DEAL_PRICE_RATIO` x median are skipped: such prices are almost
    always placeholders or bait ("1 EUR"), not bargains. (We cannot simply reuse the IQR
    filter for candidates: in a tight price cluster it would also hide genuine 25% discounts.)
    """
    priced: list[tuple[Listing, Decimal]] = []
    for listing in listings:
        price = listing.price_eur
        if price is not None:
            priced.append((listing, price))
    if len(priced) < MIN_LISTINGS_FOR_BEST_DEALS:
        return []

    kept = remove_outliers([price for _, price in priced])
    if not kept:
        return []
    median = Decimal(str(statistics.median(float(p) for p in kept)))
    if median <= 0:
        return []
    ceiling = median * Decimal(str(ratio))
    floor = median * Decimal(str(MIN_DEAL_PRICE_RATIO))

    deals: list[BestDeal] = []
    for listing, price in priced:
        if not floor <= price <= ceiling:
            continue
        discount = int(((median - price) / median * 100).to_integral_value())
        deals.append(BestDeal(listing=listing, discount_pct=discount))
    deals.sort(key=lambda d: (-d.discount_pct, d.listing.posted_at))
    return deals[:limit]
