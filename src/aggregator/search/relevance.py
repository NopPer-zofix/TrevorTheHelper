"""Relevance scoring: drop listings that do not match the expanded query ("iPhone 13" must not
return cases and chargers).

Score (0..1) = best token coverage over the query phrases (`normalized` + `variants`):
- a phrase token is covered by a text token on exact match, or on a shared long prefix for
  non-numeric words (cheap stemming: "велосипед" ~ "велосипеды"); numbers must match exactly,
- tokens that belong to `specs` ("128gb") weigh a quarter, since sellers often omit them,
- coverage in the title counts fully, coverage only via the description is discounted.

`negative_terms` are matched on the title only. A hit zeroes the score, unless the title shows the
item bundled with the accessory ("iphone 13 with charger", "iphone 13 + case").
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from aggregator.domain.models import ExpandedQuery, Listing

DEFAULT_MIN_SCORE = 0.75
_DESCRIPTION_DISCOUNT = 0.85
_SPEC_WEIGHT = 0.25  # "128gb" is two tokens, so a listing that omits storage loses only ~half

_TOKEN = re.compile(r"\w+|\+", re.UNICODE)
_LETTER_DIGIT_BOUNDARY = re.compile(r"(?<=[^\W\d_])(?=\d)|(?<=\d)(?=[^\W\d_])")
_UNIT_ALIASES = {"гб": "gb", "тб": "tb", "мб": "mb"}

# A negative hit is cancelled when a pre-marker comes before it, or a post-marker right after it.
_PRE_MARKERS = frozenset({"with", "plus", "and", "w", "+", "с", "со", "и", "вместе"})
_POST_MARKERS = frozenset(
    {"included", "incl", "includes", "bundled", "комплекте", "комплект", "включено"}
)
_POST_MARKER_WINDOW = 2


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


class RelevanceScorer:
    """Precomputes the query side once, then scores many listings."""

    def __init__(self, query: ExpandedQuery) -> None:
        self._query = query
        phrases = [tokenize(p) for p in [query.normalized, *query.variants]]
        self._phrases = [p for p in phrases if p]
        self._specs = set(tokenize(" ".join(query.specs)))

    def score(self, listing: Listing) -> float:
        if not self._phrases:
            return 1.0  # nothing to compare against: do not hide results
        title_tokens = tokenize(listing.title)
        if _has_blocking_negative(self._query, title_tokens):
            return 0.0
        full_tokens = tokenize(f"{listing.title} {listing.description or ''}")
        best = 0.0
        for phrase in self._phrases:
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
