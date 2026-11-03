"""The single interface every listing source implements."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from aggregator.domain.cities import City
from aggregator.domain.models import ExpandedQuery, Filters, Listing


class SourceError(Exception):
    """A source could not produce results (network, blocked, changed markup, disabled...).

    The orchestrator catches this (and any other exception) per source and degrades to
    partial results.
    """


def search_terms(query: ExpandedQuery, max_terms: int) -> list[str]:
    """Primary term first, then variants; case-insensitive dedupe; capped at `max_terms`."""
    seen: set[str] = set()
    terms: list[str] = []
    for candidate in [query.normalized, *query.variants]:
        cleaned = " ".join(candidate.split())
        if cleaned and cleaned.lower() not in seen:
            seen.add(cleaned.lower())
            terms.append(cleaned)
    return terms[: max(max_terms, 1)]


@runtime_checkable
class ListingSource(Protocol):
    #: Stable identifier used in config, filters, the DB and the UI ("bazaraki", "telegram").
    name: str

    async def search(
        self, query: ExpandedQuery, city: City | None, filters: Filters
    ) -> list[Listing]:
        """Return listings matching `query`.

        Sources may use `filters` to narrow the fetch but are not required to: the
        orchestrator re-applies price/sort/source filters on the merged result set.
        """
        ...
