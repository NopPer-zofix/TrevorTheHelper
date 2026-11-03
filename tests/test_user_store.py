"""DbUserStore / DbSearchLogStore against real Postgres (CI; skipped without TEST_DATABASE_URL)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from aggregator.db.models import SearchLog
from aggregator.domain.cities import City
from aggregator.services.search_service import DbSearchLogStore
from aggregator.services.users import DbUserStore


async def test_get_or_create_is_idempotent_and_updates_persist(session_factory: Any) -> None:
    store = DbUserStore(session_factory)
    first = await store.get_or_create(555, "ru")
    again = await store.get_or_create(555, "en")  # existing row wins, language not overwritten
    assert again.id == first.id
    assert (again.language, again.city, again.plan, again.is_allowed) == (
        "ru",
        None,
        "private",
        True,
    )

    await store.set_language(555, "en")
    await store.set_city(555, City.LARNACA)
    updated = await store.get_or_create(555, "ru")
    assert (updated.language, updated.city) == ("en", City.LARNACA)


async def test_search_log_rows_link_to_the_user(session_factory: Any) -> None:
    user = await DbUserStore(session_factory).get_or_create(1, "en")
    await DbSearchLogStore(session_factory).add(user.id, "iphone 13", "limassol", 12, 340)
    await DbSearchLogStore(session_factory).add(None, "bike", "all", 0, 10)

    async with session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(SearchLog))
        first = await session.scalar(select(SearchLog).where(SearchLog.query == "iphone 13"))
    assert count == 2
    assert first is not None and first.user_id == user.id and first.result_count == 12
