"""Repository tests against a real Postgres (skipped unless TEST_DATABASE_URL is set)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aggregator.db.repositories import ListingRepository
from aggregator.domain.cities import City
from aggregator.domain.models import Listing

SOURCE = "telegram"


def make_listing(
    external_id: str,
    title: str,
    *,
    description: str | None = None,
    city: City = City.LIMASSOL,
    price: str | None = "100",
    age_days: float = 1,
) -> Listing:
    return Listing(
        source=SOURCE,
        external_id=external_id,
        url=f"https://t.me/test/{external_id}",
        title=title,
        description=description,
        price_amount=Decimal(price) if price else None,
        currency="EUR" if price else None,
        city=city,
        posted_at=datetime.now(UTC) - timedelta(days=age_days),
    )


@pytest.fixture
def repo(session_factory: async_sessionmaker[AsyncSession]) -> ListingRepository:
    return ListingRepository(session_factory)


async def test_upsert_inserts_then_updates_in_place(repo: ListingRepository) -> None:
    await repo.upsert(make_listing("1:1", "Trek bike", price="200"))
    await repo.upsert(make_listing("1:1", "Trek bike", price="150"))

    found = await repo.search(SOURCE, ["trek"], None, max_age_days=30)
    assert len(found) == 1
    assert found[0].price_amount == Decimal("150.00")


async def test_search_matches_title_and_description(repo: ListingRepository) -> None:
    await repo.upsert(make_listing("1:1", "Sofa", description="Grey IKEA corner sofa"))
    await repo.upsert(make_listing("1:2", "Desk"))

    found = await repo.search(SOURCE, ["ikea"], None, max_age_days=30)
    assert [item.external_id for item in found] == ["1:1"]


async def test_trigram_branch_matches_inflected_russian(repo: ListingRepository) -> None:
    await repo.upsert(make_listing("1:1", "Велосипед Trek FX 2"))
    await repo.upsert(make_listing("1:2", "Диван угловой"))

    found = await repo.search(SOURCE, ["велосипеды"], None, max_age_days=30)
    assert [item.external_id for item in found] == ["1:1"]


async def test_any_variant_matches(repo: ListingRepository) -> None:
    await repo.upsert(make_listing("1:1", "Велосипед"))
    await repo.upsert(make_listing("1:2", "Bicycle"))
    await repo.upsert(make_listing("1:3", "Sofa"))

    found = await repo.search(SOURCE, ["bicycle", "велосипед"], None, max_age_days=30)
    assert {item.external_id for item in found} == {"1:1", "1:2"}


async def test_full_text_hit_ranks_above_fuzzy_hit(repo: ListingRepository) -> None:
    await repo.upsert(make_listing("1:1", "Велосипеды детские", age_days=1))
    await repo.upsert(make_listing("1:2", "Велосипед взрослый", age_days=5))

    found = await repo.search(SOURCE, ["велосипед"], None, max_age_days=30)
    assert [item.external_id for item in found] == ["1:2", "1:1"]


async def test_city_filter_excludes_unknown_for_specific_city(repo: ListingRepository) -> None:
    await repo.upsert(make_listing("1:1", "Bike", city=City.LIMASSOL))
    await repo.upsert(make_listing("1:2", "Bike", city=City.PAPHOS))
    await repo.upsert(make_listing("1:3", "Bike", city=City.UNKNOWN))

    limassol = await repo.search(SOURCE, ["bike"], City.LIMASSOL, max_age_days=30)
    assert [item.external_id for item in limassol] == ["1:1"]

    everywhere = await repo.search(SOURCE, ["bike"], City.ALL_CYPRUS, max_age_days=30)
    assert {item.external_id for item in everywhere} == {"1:1", "1:2", "1:3"}


async def test_max_age_and_inactive_are_excluded(repo: ListingRepository) -> None:
    await repo.upsert(make_listing("1:1", "Bike fresh", age_days=2))
    await repo.upsert(make_listing("1:2", "Bike stale", age_days=60))
    await repo.upsert(make_listing("1:3", "Bike sold"), is_active=False)

    found = await repo.search(SOURCE, ["bike"], None, max_age_days=30)
    assert [item.external_id for item in found] == ["1:1"]


async def test_mark_deleted(repo: ListingRepository) -> None:
    await repo.upsert(make_listing("1:1", "Bike"))
    await repo.upsert(make_listing("1:2", "Bike"))

    assert await repo.mark_deleted(SOURCE, ["1:1", "9:9"]) == 1
    assert await repo.mark_deleted(SOURCE, []) == 0
    found = await repo.search(SOURCE, ["bike"], None, max_age_days=30)
    assert [item.external_id for item in found] == ["1:2"]


async def test_deactivate_older_than(repo: ListingRepository) -> None:
    await repo.upsert(make_listing("1:1", "Bike", age_days=2))
    await repo.upsert(make_listing("1:2", "Bike", age_days=40))

    cutoff = datetime.now(UTC) - timedelta(days=30)
    assert await repo.deactivate_older_than(SOURCE, cutoff) == 1
    found = await repo.search(SOURCE, ["bike"], None, max_age_days=365)
    assert [item.external_id for item in found] == ["1:1"]


async def test_blank_terms_return_nothing(repo: ListingRepository) -> None:
    await repo.upsert(make_listing("1:1", "Bike"))
    assert await repo.search(SOURCE, ["", "  "], None, max_age_days=30) == []


async def test_deactivate_where_hides_only_what_the_predicate_rejects(
    repo: ListingRepository,
) -> None:
    await repo.upsert(make_listing("1:1", "Bike", description="good bike"))
    await repo.upsert(make_listing("1:2", "Bike spam", description="earn money"))
    await repo.upsert(make_listing("1:3", "Bike", description=None))

    hidden = await repo.deactivate_where(
        SOURCE, lambda title, description: "spam" in title or "earn" in (description or "")
    )

    assert hidden == 1
    found = await repo.search(SOURCE, ["bike"], None, max_age_days=30)
    assert sorted(item.external_id for item in found) == ["1:1", "1:3"]
    # a second run has nothing left to hide
    assert await repo.deactivate_where(SOURCE, lambda title, description: "spam" in title) == 0
