"""Persistent cache of LLM expansions, keyed by normalised input (`query_expansions` table)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aggregator.db.models import QueryExpansion
from aggregator.domain.models import ExpandedQuery


class ExpansionStore(Protocol):
    async def get(self, normalized_input: str, *, original: str) -> ExpandedQuery | None: ...

    async def put(self, normalized_input: str, expansion: ExpandedQuery) -> None: ...


def _payload(expansion: ExpandedQuery) -> dict[str, Any]:
    # `original` is per-request text, not part of what is cached.
    return expansion.model_dump(mode="json", exclude={"original"})


def _revive(payload: dict[str, Any], original: str) -> ExpandedQuery | None:
    try:
        return ExpandedQuery.model_validate({**payload, "original": original})
    except ValidationError:
        return None  # schema drifted since it was cached: treat as a miss


class DbExpansionStore:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        max_age_days: int = 30,
    ) -> None:
        self._session_factory = session_factory
        self._max_age = timedelta(days=max_age_days)

    async def get(self, normalized_input: str, *, original: str) -> ExpandedQuery | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(QueryExpansion).where(QueryExpansion.normalized_input == normalized_input)
            )
        if row is None:
            return None
        if row.created_at < datetime.now(UTC) - self._max_age:
            return None  # stale; the next put() overwrites it
        return _revive(row.payload, original)

    async def put(self, normalized_input: str, expansion: ExpandedQuery) -> None:
        payload = _payload(expansion)
        stmt = pg_insert(QueryExpansion).values(normalized_input=normalized_input, payload=payload)
        stmt = stmt.on_conflict_do_update(
            index_elements=[QueryExpansion.normalized_input],
            set_={"payload": payload, "created_at": datetime.now(UTC)},
        )
        async with self._session_factory() as session, session.begin():
            await session.execute(stmt)

    async def purge_older_than(self, days: int) -> int:
        cutoff = datetime.now(UTC) - timedelta(days=days)
        async with self._session_factory() as session, session.begin():
            result = await session.execute(
                delete(QueryExpansion).where(QueryExpansion.created_at < cutoff)
            )
        return int(getattr(result, "rowcount", 0) or 0)


class InMemoryExpansionStore:
    """Test double / DB-less mode."""

    def __init__(self) -> None:
        self._rows: dict[str, dict[str, Any]] = {}

    async def get(self, normalized_input: str, *, original: str) -> ExpandedQuery | None:
        payload = self._rows.get(normalized_input)
        return None if payload is None else _revive(payload, original)

    async def put(self, normalized_input: str, expansion: ExpandedQuery) -> None:
        self._rows[normalized_input] = _payload(expansion)
