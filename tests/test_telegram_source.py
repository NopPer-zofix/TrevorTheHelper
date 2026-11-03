from __future__ import annotations

from typing import Any

import pytest

from aggregator.domain.cities import City
from aggregator.domain.models import ExpandedQuery, Filters
from aggregator.sources.base import ListingSource, SourceError
from aggregator.sources.telegram.source import TelegramSource


class StubRepo:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def search(self, source: str, terms: Any, city: Any, max_age_days: int) -> list[Any]:
        if self.error:
            raise self.error
        self.calls.append(
            {"source": source, "terms": list(terms), "city": city, "max_age_days": max_age_days}
        )
        return []


def query(**kwargs: Any) -> ExpandedQuery:
    return ExpandedQuery(original="bike", normalized="bike", **kwargs)


async def test_passes_deduped_terms_city_and_age_to_the_repository() -> None:
    repo = StubRepo()
    source = TelegramSource(repo, max_age_days=14, max_terms=3)  # type: ignore[arg-type]

    await source.search(
        query(variants=["Bike", "велосипед", "bicycle", "extra"]), City.PAPHOS, Filters()
    )

    assert repo.calls == [
        {
            "source": "telegram",
            "terms": ["bike", "велосипед", "bicycle"],
            "city": City.PAPHOS,
            "max_age_days": 14,
        }
    ]


async def test_repository_failure_becomes_source_error() -> None:
    source = TelegramSource(StubRepo(RuntimeError("db down")))  # type: ignore[arg-type]
    with pytest.raises(SourceError):
        await source.search(query(), None, Filters())


def test_satisfies_the_listing_source_protocol() -> None:
    assert isinstance(TelegramSource(StubRepo()), ListingSource)  # type: ignore[arg-type]
