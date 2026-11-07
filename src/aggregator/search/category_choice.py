"""Decide whether to ask the user which category they mean, and what to ask.

Input is a sample of where a source's results fall ({"telephones/mobile-phones": 52, "telephones/
accessories": 6}), taken from one unscoped results page. Walking down the category tree one level
at a time:

- if one option clearly dominates (DOMINANT_SHARE) it is picked silently: "iphone 13" is phones;
- if the options are genuinely split, ask: "3 bedroom apartment" is a mix of flats and houses,
  for sale and to rent, which are different searches;
- rent versus sale is *always* asked when both appear, because the sample is dominated by sale
  ads (about 3.5x more of them on the site) and silently picking the majority would hide the
  rentals from someone who wants one. A rent/sale word in the query ("rent", "аренда") answers it;
- too small a sample (MIN_SAMPLE) decides nothing: search without a category.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from aggregator.domain.categories import MAX_DEPTH, is_offered

DOMINANT_SHARE = 0.85
MIN_OPTION_SHARE = 0.05
MAX_OPTIONS = 6
MIN_SAMPLE = 8
MIN_PROPERTY_COUNT = 2  # ads needed before the minority of rent / sale is worth a question

RENT = "real-estate-to-rent"
SALE = "real-estate-for-sale"
_ALWAYS_ASK = frozenset({RENT, SALE})

Intent = Literal["rent", "sale"]

_RENT_WORDS = frozenset(
    {"rent", "rental", "rentals", "аренда", "аренду", "сдам", "сдаётся", "сдается", "снять",
     "сниму", "посуточно"}
)  # fmt: skip
_SALE_WORDS = frozenset({"sale", "buy", "purchase", "продам", "продажа", "купить", "покупка"})
_WORD = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True)
class CategoryOption:
    path: str
    count: int


@dataclass(frozen=True)
class Ask:
    """Ask the user to pick one of `options`, which are the children of `prefix` (None = top)."""

    prefix: str | None
    options: tuple[CategoryOption, ...]


@dataclass(frozen=True)
class Resolved:
    """Search in `path` (None = no category scope)."""

    path: str | None


Decision = Ask | Resolved


def intent_of(text: str) -> Intent | None:
    """Rent / sale intent stated in the query itself ("2 bedroom apartment for rent")."""
    words = {w.casefold() for w in _WORD.findall(text)}
    rent, sale = bool(words & _RENT_WORDS), bool(words & _SALE_WORDS)
    if rent == sale:  # neither, or contradictory
        return None
    return "rent" if rent else "sale"


def _children(counts: Mapping[str, int], prefix: str | None) -> list[CategoryOption]:
    """Counts grouped by the next path segment below `prefix`, adult categories left out."""
    grouped: dict[str, int] = defaultdict(int)
    for path, count in counts.items():
        if count <= 0:
            continue
        parts = path.split("/")
        if prefix is None:
            key = parts[0]
        elif path.startswith(prefix + "/") and len(parts) == prefix.count("/") + 2:
            key = "/".join(parts[: prefix.count("/") + 2])
        else:
            continue
        if is_offered(key):
            grouped[key] += count
    return sorted((CategoryOption(p, n) for p, n in grouped.items()), key=lambda o: -o.count)


def decide(
    counts: Mapping[str, int], prefix: str | None = None, intent: Intent | None = None
) -> Decision:
    """The next step, given the category sample and the part of the path already settled."""
    while True:
        if prefix is not None and prefix.count("/") + 1 >= MAX_DEPTH:
            return Resolved(prefix)
        options = _children(counts, prefix)
        total = sum(o.count for o in options)
        if total < MIN_SAMPLE:
            return Resolved(prefix)  # too little evidence to ask, or to narrow, anything

        by_path = {o.path: o for o in options}
        if prefix is None and intent is not None:
            wanted = RENT if intent == "rent" else SALE
            if wanted in by_path:
                prefix = wanted
                continue

        shown = [o for o in options if o.count / total >= MIN_OPTION_SHARE][:MAX_OPTIONS]
        top = options[0]
        # Rent and sale are different searches. Sale ads outnumber rentals about 3.5 to 1, so the
        # minority must be offered however small its share in the sample (a few ads are enough).
        both_property_kinds = prefix is None and all(
            p in by_path and by_path[p].count >= MIN_PROPERTY_COUNT for p in _ALWAYS_ASK
        )
        if both_property_kinds:
            shown = [o for o in options if o in shown or o.path in _ALWAYS_ASK][:MAX_OPTIONS]
        if not both_property_kinds and (top.count / total >= DOMINANT_SHARE or len(shown) <= 1):
            prefix = top.path
            continue
        return Ask(prefix=prefix, options=tuple(shown))
