"""Relevance scoring: drop listings that do not match the expanded query ("iPhone 13" must not
return cases and chargers).

Score (0..1) = best token coverage over the query phrases (`normalized` + `variants`):
- a phrase token is covered by a text token on exact match, or on a shared long prefix for
  non-numeric words (cheap stemming: "велосипед" ~ "велосипеды"); numbers must match exactly,
- tokens that belong to `specs` ("128gb") weigh a quarter, since sellers often omit them,
- coverage in the title counts fully, coverage only via the description is discounted.

`negative_terms` are matched on the title only. A hit zeroes the score, unless the title shows the
item bundled with the accessory ("iphone 13 with charger", "iphone 13 + case").

Three stricter checks, all on the title and all zeroing the score:
- leading part nouns: "Display apple iphone 13", "Battery apple iphone 13". A part word that comes
  *before* the product name makes the part the subject of the ad. The same word after the product
  ("iphone 13 | 100 battery | box, cable") is just a description of a real phone, so it is allowed;
- model tier: the query "iphone 13" must not match "iphone 13 Pro Max" (a different, pricier
  product that would distort the statistics). Tier words after the model number must also be in
  the query;
- storage: a title that states a storage size which differs from the one asked for is a different
  variant ("128gb" asked, "256gb" in the title).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from itertools import pairwise

from aggregator.domain.models import ExpandedQuery, Listing

DEFAULT_MIN_SCORE = 0.75
_DESCRIPTION_DISCOUNT = 0.85
_SPEC_WEIGHT = 0.25  # "128gb" is two tokens, so a listing that omits storage loses only ~half

_TOKEN = re.compile(r"\w+|[+&]", re.UNICODE)
_LETTER_DIGIT_BOUNDARY = re.compile(r"(?<=[^\W\d_])(?=\d)|(?<=\d)(?=[^\W\d_])")
_UNIT_ALIASES = {"гб": "gb", "тб": "tb", "мб": "mb"}

# A negative hit is cancelled when a pre-marker comes before it, or a post-marker right after it.
_PRE_MARKERS = frozenset(
    {
        "with", "plus", "and", "w", "+", "&", "box", "boxed",
        "с", "со", "и", "вместе", "коробка", "коробкой",
    }
)  # fmt: skip
_POST_MARKERS = frozenset(
    {"included", "incl", "includes", "bundled", "комплекте", "комплект", "включено"}
)
_POST_MARKER_WINDOW = 2

# Words that name a different product tier when they follow the model number.
_TIER_WORDS = frozenset(
    {
        "pro", "max", "mini", "plus", "ultra", "lite", "fe", "air", "promax",
        "про", "макс", "мини", "плюс", "ультра", "лайт",
    }
)  # fmt: skip
_TIER_WINDOW = 2  # tokens after the model number that are inspected
_STORAGE_UNITS = frozenset({"gb", "tb"})

# Part / accessory nouns that, when they LEAD the title, mean the ad is for the part. Keyed by the
# `category_hint` produced by query expansion.
_LEADING_PART_TERMS: dict[str, frozenset[str]] = {
    "phone": frozenset(
        {
            "display", "screen", "lcd", "oled", "battery", "glass", "buzzer", "speaker", "flex",
            "housing", "motherboard", "cable", "adapter", "protector", "holder", "tempered",
            "charger",
            "дисплей", "экран", "аккумулятор", "батарея", "стекло", "динамик", "плата",
            "шлейф", "корпус", "кабель", "держатель", "зарядка",
        }
    ),
}  # fmt: skip
_LEADING_PART_TERMS["tablet"] = _LEADING_PART_TERMS["phone"]
_LEADING_PART_TERMS["laptop"] = frozenset(
    {
        "screen", "display", "battery", "keyboard", "motherboard", "fan", "charger", "adapter",
        "hinge", "palmrest", "bag", "sleeve",
        "экран", "дисплей", "аккумулятор", "клавиатура", "зарядка", "сумка",
    }
)  # fmt: skip


def tokenize(text: str) -> list[str]:
    """Lowercased word tokens with letters and digits split ("iphone13" -> "iphone", "13")."""
    lowered = text.casefold().replace("ё", "е")
    tokens: list[str] = []
    for raw in _TOKEN.findall(lowered):
        for part in _LETTER_DIGIT_BOUNDARY.sub(" ", raw).split():
            tokens.append(_UNIT_ALIASES.get(part, part))
    return tokens


def _tokens_match(query_token: str, text_token: str) -> bool:
    if query_token == text_token:
        return True
    if query_token.isdigit() or text_token.isdigit():
        return False
    shorter = min(len(query_token), len(text_token))
    if shorter < 4:
        return False
    longer = max(len(query_token), len(text_token))
    prefix = 0
    for a, b in zip(query_token, text_token, strict=False):
        if a != b:
            break
        prefix += 1
    return prefix >= max(4, longer - 3, shorter - 2)


def _covered(token: str, text_tokens: Sequence[str], text_set: set[str]) -> bool:
    return token in text_set or any(_tokens_match(token, t) for t in text_tokens)


def _coverage(phrase: Sequence[str], text_tokens: Sequence[str], spec_tokens: set[str]) -> float:
    text_set = set(text_tokens)
    total = matched = 0.0
    for token in phrase:
        weight = _SPEC_WEIGHT if token in spec_tokens else 1.0
        total += weight
        if _covered(token, text_tokens, text_set):
            matched += weight
    return matched / total if total else 0.0


def _first_index(term: Sequence[str], title_tokens: Sequence[str]) -> int | None:
    """Position of the term in the title if every one of its tokens is present, else None."""
    positions: list[int] = []
    for token in term:
        found = next((i for i, t in enumerate(title_tokens) if _tokens_match(token, t)), None)
        if found is None:
            return None
        positions.append(found)
    return min(positions)


def _is_bundled(index: int, title_tokens: Sequence[str]) -> bool:
    if any(t in _PRE_MARKERS for t in title_tokens[:index]):
        return True
    window = title_tokens[index + 1 : index + 1 + _POST_MARKER_WINDOW + 1]
    return any(t in _POST_MARKERS for t in window)


def _has_blocking_negative(query: ExpandedQuery, title_tokens: Sequence[str]) -> bool:
    for term in query.negative_terms:
        tokens = tokenize(term)
        if not tokens:
            continue
        index = _first_index(tokens, title_tokens)
        if index is not None and not _is_bundled(index, title_tokens):
            return True
    return False


def _storage_values(tokens: Sequence[str]) -> set[str]:
    """Storage sizes stated in the tokens: ["128", "gb"] -> {"128gb"}."""
    return {
        f"{number}{unit}"
        for number, unit in pairwise(tokens)
        if number.isdigit() and unit in _STORAGE_UNITS
    }


def _tier_mismatch(phrase: Sequence[str], title_tokens: Sequence[str]) -> bool:
    """True if the title adds a tier word ("pro", "max"...) right after a model number of the
    phrase that the phrase itself does not have."""
    allowed = set(phrase)
    for number in (t for t in phrase if t.isdigit()):
        for index, token in enumerate(title_tokens):
            if token != number:
                continue
            following = title_tokens[index + 1 : index + 1 + _TIER_WINDOW]
            if any(word in _TIER_WORDS and word not in allowed for word in following):
                return True
    return False


class RelevanceScorer:
    """Precomputes the query side once, then scores many listings."""

    def __init__(self, query: ExpandedQuery) -> None:
        self._query = query
        phrases = [tokenize(p) for p in [query.normalized, *query.variants]]
        self._phrases = [p for p in phrases if p]
        self._specs = set(tokenize(" ".join(query.specs)))
        every_token = [t for phrase in self._phrases for t in phrase] + tokenize(
            " ".join(query.specs)
        )
        self._storage = _storage_values(every_token)
        # The words of the product name itself (no numbers, no specs): where the product starts.
        self._name_tokens = (
            {t for phrase in self._phrases for t in phrase if not t.isdigit() and len(t) >= 3}
            - self._specs
            - _STORAGE_UNITS
        )
        self._part_terms = _LEADING_PART_TERMS.get(
            (query.category_hint or "").casefold(), frozenset()
        )

    def _leads_with_part(self, title_tokens: Sequence[str]) -> bool:
        if not self._part_terms:
            return False
        first = next(
            (
                i
                for i, token in enumerate(title_tokens)
                if any(_tokens_match(name, token) for name in self._name_tokens)
            ),
            None,
        )
        return first is not None and any(t in self._part_terms for t in title_tokens[:first])

    def score(self, listing: Listing) -> float:
        if not self._phrases:
            return 1.0  # nothing to compare against: do not hide results
        title_tokens = tokenize(listing.title)
        if _has_blocking_negative(self._query, title_tokens):
            return 0.0
        if self._leads_with_part(title_tokens):
            return 0.0
        title_storage = _storage_values(title_tokens)
        if self._storage and title_storage and self._storage.isdisjoint(title_storage):
            return 0.0
        full_tokens = tokenize(f"{listing.title} {listing.description or ''}")
        best = 0.0
        for phrase in self._phrases:
            if _tier_mismatch(phrase, title_tokens):
                continue
            title_cov = _coverage(phrase, title_tokens, self._specs)
            full_cov = _coverage(phrase, full_tokens, self._specs)
            best = max(best, title_cov, _DESCRIPTION_DISCOUNT * full_cov)
        return best


def relevance_score(listing: Listing, query: ExpandedQuery) -> float:
    return RelevanceScorer(query).score(listing)


def filter_relevant(
    listings: Iterable[Listing],
    query: ExpandedQuery,
    min_score: float = DEFAULT_MIN_SCORE,
) -> list[Listing]:
    scorer = RelevanceScorer(query)
    return [listing for listing in listings if scorer.score(listing) >= min_score]
