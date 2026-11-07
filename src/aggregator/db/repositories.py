"""Persistence for indexed listings (written by the Telegram indexer, read by TelegramSource)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, case, func, literal, literal_column, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aggregator.db.models import Listing as ListingRow
from aggregator.domain.areas import locate
from aggregator.domain.cities import City
from aggregator.domain.models import Listing

MAX_SEARCH_TERMS = 10
DEFAULT_SEARCH_LIMIT = 200

# The 'simple' FTS config does no stemming, so plural/case forms ("велосипеды" vs "велосипед")
# only match through the trigram branch (`title %> term`, pg_trgm word similarity).
_SIMPLE: ColumnElement[Any] = literal_column("'simple'::regconfig")


class ListingRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def upsert(
        self,
        listing: Listing,
        *,
        is_active: bool = True,
        raw: dict[str, Any] | None = None,
    ) -> None:
        """Insert, or update in place on (source, external_id). Refreshes `last_seen_at`."""
        values: dict[str, Any] = {
            "source": listing.source,
            "external_id": listing.external_id,
            "url": listing.url,
            "title": listing.title,
            "description": listing.description,
            "price_amount": listing.price_amount,
            "currency": listing.currency,
            "city": listing.city.value,
            "posted_at": listing.posted_at,
            "is_active": is_active,
            "raw": raw,
        }
        stmt = pg_insert(ListingRow).values(**values)
        update_values = {k: v for k, v in values.items() if k not in {"source", "external_id"}}
        update_values["last_seen_at"] = func.now()
        stmt = stmt.on_conflict_do_update(
            constraint="uq_listings_source_external_id", set_=update_values
        )
        async with self._session_factory() as session, session.begin():
            await session.execute(stmt)

    async def mark_deleted(self, source: str, external_ids: Sequence[str]) -> int:
        """Deactivate listings whose message was deleted. Returns the number of rows changed."""
        if not external_ids:
            return 0
        stmt = (
            update(ListingRow)
            .where(
                ListingRow.source == source,
                ListingRow.external_id.in_(list(external_ids)),
                ListingRow.is_active.is_(True),
            )
            .values(is_active=False)
        )
        async with self._session_factory() as session, session.begin():
            result = await session.execute(stmt)
        return int(getattr(result, "rowcount", 0) or 0)

    async def deactivate_older_than(self, source: str, cutoff: datetime) -> int:
        """Retention: deactivate active listings posted before `cutoff`."""
        stmt = (
            update(ListingRow)
            .where(
                ListingRow.source == source,
                ListingRow.is_active.is_(True),
                ListingRow.posted_at < cutoff,
            )
            .values(is_active=False)
        )
        async with self._session_factory() as session, session.begin():
            result = await session.execute(stmt)
        return int(getattr(result, "rowcount", 0) or 0)

    async def deactivate_where(
        self, source: str, is_unwanted: Callable[[str, str | None], bool]
    ) -> int:
        """Deactivate active listings whose (title, description) the predicate rejects.

        Used to clean out spam that was stored before a rule existed. Rows stay in the table
        (is_active=False), so nothing is lost and a wrong rule can be undone.
        """
        stmt = select(ListingRow.id, ListingRow.title, ListingRow.description).where(
            ListingRow.source == source, ListingRow.is_active.is_(True)
        )
        async with self._session_factory() as session:
            rows = (await session.execute(stmt)).all()
        ids = [row.id for row in rows if is_unwanted(row.title, row.description)]
        if not ids:
            return 0
        async with self._session_factory() as session, session.begin():
            result = await session.execute(
                update(ListingRow).where(ListingRow.id.in_(ids)).values(is_active=False)
            )
        return int(getattr(result, "rowcount", 0) or 0)

    async def search(
        self,
        source: str,
        terms: Sequence[str],
        city: City | None,
        max_age_days: int,
        limit: int = DEFAULT_SEARCH_LIMIT,
    ) -> list[Listing]:
        """Active listings matching any of `terms` (FTS or trigram word similarity), best first."""
        cleaned = list(dict.fromkeys(t.strip() for t in terms if t and t.strip()))[
            :MAX_SEARCH_TERMS
        ]
        if not cleaned:
            return []

        matches: list[ColumnElement[bool]] = []
        scores: list[ColumnElement[float]] = []
        for term in cleaned:
            fts = ListingRow.search_vector.op("@@")(func.plainto_tsquery(_SIMPLE, term))
            trigram = ListingRow.title.op("%>")(term)
            matches += [fts, trigram]
            # A full-text hit outranks a fuzzy one; word similarity orders within each group.
            scores.append(
                case((fts, literal(1.0)), else_=literal(0.0))
                + func.word_similarity(term, ListingRow.title)
            )

        cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
        stmt = (
            select(ListingRow)
            .where(
                ListingRow.source == source,
                ListingRow.is_active.is_(True),
                ListingRow.posted_at >= cutoff,
                or_(*matches),
            )
            .order_by(func.greatest(*scores).desc(), ListingRow.posted_at.desc())
            .limit(limit)
        )
        if city is not None and city is not City.ALL_CYPRUS:
            stmt = stmt.where(ListingRow.city == city.value)

        async with self._session_factory() as session:
            rows = (await session.execute(stmt)).scalars().all()
        return [_to_domain(row) for row in rows]


def _to_domain(row: ListingRow) -> Listing:
    try:
        city = City(row.city) if row.city else City.UNKNOWN
    except ValueError:
        city = City.UNKNOWN
    if city is City.ALL_CYPRUS:  # a search scope, never a listing's own city
        city = City.UNKNOWN
    # The neighbourhood is not a column: it is read from the text each time, so improving the
    # spelling tables takes effect for listings that were stored long ago.
    area = locate(f"{row.title}\n{row.description or ''}", city)[1]
    return Listing(
        source=row.source,
        external_id=row.external_id,
        url=row.url,
        title=row.title,
        description=row.description,
        price_amount=row.price_amount,
        currency=row.currency,
        city=city,
        area=area,
        posted_at=row.posted_at,
    )
