"""Cache-key normalisation and cleanup of expansions (shared by the LLM and fallback paths)."""

from __future__ import annotations

import re
import unicodedata

from aggregator.domain.models import ExpandedQuery

MAX_INPUT_CHARS = 128
MAX_VARIANTS = 8
MAX_NEGATIVE_TERMS = 12
MAX_SPECS = 6
_MAX_TERM_CHARS = 60

_PUNCTUATION = re.compile(r"[^\w\s+.\-]", re.UNICODE)
_SPACES = re.compile(r"\s+")


def normalize_input(text: str) -> str:
    """Canonical form of a user query, used as the cache key.

    Case-folded, NFKC, punctuation (other than `+ . -`) turned into spaces, whitespace collapsed,
    and capped at `MAX_INPUT_CHARS`. "iPhone 13, 128GB!" and "iphone 13 128gb" share a key.
    """
    text = unicodedata.normalize("NFKC", text).casefold()
    text = _PUNCTUATION.sub(" ", text)
    tokens = [token.strip(".-") for token in _SPACES.split(text)]
    return " ".join(token for token in tokens if token)[:MAX_INPUT_CHARS].strip()


def _clean_terms(terms: list[str], *, limit: int, exclude: set[str] | None = None) -> list[str]:
    seen: set[str] = set(exclude or ())
    cleaned: list[str] = []
    for term in terms:
        value = normalize_input(term)[:_MAX_TERM_CHARS]
        if value and value not in seen:
            seen.add(value)
            cleaned.append(value)
        if len(cleaned) >= limit:
            break
    return cleaned


def clean_expansion(query: ExpandedQuery) -> ExpandedQuery:
    """Normalise, dedupe and cap every list; guarantee the invariants the pipeline relies on.

    - `normalized` is never empty (falls back to the normalised original).
    - `variants` never repeat `normalized`.
    - `negative_terms` never contain a word the user actually searched for (searching for
      "iphone case" must not exclude cases).
    """
    normalized = normalize_input(query.normalized) or normalize_input(query.original)
    searched_words = set(normalize_input(query.original).split()) | set(normalized.split())
    return ExpandedQuery(
        original=query.original,
        normalized=normalized,
        brand=_clean_single(query.brand),
        model=_clean_single(query.model),
        specs=_clean_terms(query.specs, limit=MAX_SPECS),
        variants=_clean_terms(query.variants, limit=MAX_VARIANTS, exclude={normalized}),
        negative_terms=[
            term
            for term in _clean_terms(query.negative_terms, limit=MAX_NEGATIVE_TERMS * 2)
            if not (set(term.split()) & searched_words)
        ][:MAX_NEGATIVE_TERMS],
        category_hint=_clean_single(query.category_hint),
    )


def _clean_single(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.split())[:_MAX_TERM_CHARS]
    return cleaned or None
