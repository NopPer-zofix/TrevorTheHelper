"""Split a set of prices into "cases": normal, unusually low, unusually high.

Why: a search for "iphone 13" mostly returns phones around EUR 300, but also a few cases at EUR 2,
displays at EUR 40 and the odd EUR 5,000 typo. Those drag averages and medians around and clutter
the list. They are *not* the same kind of thing as the main group, so we separate them.

Algorithm (all on log prices, because prices are multiplicative: EUR 300 -> 150 is as far from the
centre as 300 -> 600):
1. centre = median of log prices; spread = 1.4826 * MAD (the robust equivalent of a standard
   deviation), never below MIN_SPREAD so a tight cluster does not turn every small difference into
   an "outlier";
2. a price is unusual when it lies more than K spreads from the centre;
3. repeat once on the survivors only. The first pass is distorted when many junk prices are present
   (the median shifts, the spread inflates); the second pass sees mostly the real cluster;
4. before all that, look for a dominant group: sort the log prices and cut at big gaps (a price
   ratio above GAP_RATIO). If no resulting cluster holds at least DOMINANT_SHARE of the listings
   the result set is genuinely mixed (say, half phones and half chargers); then nothing is flagged,
   because hiding either half would be a guess. The median/MAD rule alone cannot see this: its
   boundaries simply become absurdly wide.

Fewer than MIN_PRICED prices: not enough data to call anything unusual.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise

MIN_PRICED = 6
K = 3.5
MIN_SPREAD = 0.35
PASSES = 2
GAP_RATIO = 3.0  # two neighbouring prices this far apart belong to different groups
DOMINANT_SHARE = 0.6
_MAD_TO_SIGMA = 1.4826


class PriceCase(StrEnum):
    NORMAL = "normal"
    LOW = "low"  # likely a part, accessory, placeholder or bait price
    HIGH = "high"  # likely a typo or a different class of product


@dataclass(frozen=True)
class PriceCuts:
    """The boundaries found for one result set. All fields None/False = nothing is unusual."""

    low_below: Decimal | None = None  # prices strictly below this are LOW
    high_above: Decimal | None = None  # prices strictly above this are HIGH
    mixed: bool = False  # True when no dominant price group exists, so nothing was flagged

    def case_of(self, price: Decimal | None) -> PriceCase:
        if price is None or self.low_below is None or self.high_above is None:
            return PriceCase.NORMAL
        if price <= 0 or price < self.low_below:
            return PriceCase.LOW
        if price > self.high_above:
            return PriceCase.HIGH
        return PriceCase.NORMAL


def _bounds(sample: Sequence[float]) -> tuple[float, float]:
    logs = [math.log(p) for p in sample]
    centre = statistics.median(logs)
    mad = statistics.median(abs(x - centre) for x in logs)
    spread = max(_MAD_TO_SIGMA * mad, MIN_SPREAD)
    return math.exp(centre - K * spread), math.exp(centre + K * spread)


def _largest_group_share(sorted_prices: Sequence[float]) -> float:
    """Share of the prices that sit in the biggest cluster (clusters are split at big gaps)."""
    biggest = current = 1
    for previous, price in pairwise(sorted_prices):
        current = 1 if price / previous > GAP_RATIO else current + 1
        biggest = max(biggest, current)
    return biggest / len(sorted_prices)


def find_price_cuts(prices: Sequence[Decimal]) -> PriceCuts:
    positive = sorted(float(p) for p in prices if p > 0)
    if len(positive) < MIN_PRICED:
        return PriceCuts()
    if _largest_group_share(positive) < DOMINANT_SHARE:
        return PriceCuts(mixed=True)

    sample = positive
    low, high = _bounds(sample)
    for _ in range(PASSES - 1):
        survivors = [p for p in positive if low <= p <= high]
        if len(survivors) < MIN_PRICED or len(survivors) == len(sample):
            break
        sample = survivors
        low, high = _bounds(sample)

    return PriceCuts(low_below=Decimal(str(round(low, 2))), high_above=Decimal(str(round(high, 2))))
