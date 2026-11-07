"""Decide what to store for one Telegram message. Pure logic plus repository calls; no Telethon."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from aggregator.domain.models import Listing
from aggregator.sources.telegram.parser import parse_message

SOURCE_NAME = "telegram"


class ListingWriter(Protocol):
    async def upsert(
        self, listing: Listing, *, is_active: bool = True, raw: dict[str, Any] | None = None
    ) -> None: ...

    async def mark_deleted(self, source: str, external_ids: list[str]) -> int: ...


class IngestAction(StrEnum):
    STORED = "stored"
    STORED_INACTIVE = "stored_inactive"  # sold: kept for the record, hidden from search
    SKIPPED_WANTED = "skipped_wanted"
    SKIPPED_EMPTY = "skipped_empty"
    SKIPPED_SPAM = "skipped_spam"  # recruitment / earn-money bots, link-only posts, Chinese text


def external_id(chat_id: int, message_id: int) -> str:
    """`chat_id` is the real (unmarked, positive) id, e.g. from `telethon.utils.resolve_id`."""
    return f"{chat_id}:{message_id}"


def message_url(chat_id: int, message_id: int, username: str | None) -> str:
    if username:
        return f"https://t.me/{username}/{message_id}"
    return f"https://t.me/c/{chat_id}/{message_id}"  # private group: only members can open it


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


async def ingest_message(
    repository: ListingWriter,
    *,
    chat_id: int,
    message_id: int,
    username: str | None,
    text: str | None,
    posted_at: datetime,
    deactivate_existing: bool = True,
) -> IngestAction:
    """Store, update or hide the listing for one message.

    `deactivate_existing` should be True for live events (an edit can turn a stored post into a
    "wanted" post or remove its text) and False for backfill, where nothing is stored yet.
    """
    ext_id = external_id(chat_id, message_id)
    parsed = parse_message(text or "")

    skipped: IngestAction | None = None
    if not parsed.title:
        skipped = IngestAction.SKIPPED_EMPTY
    elif parsed.spam is not None:
        skipped = IngestAction.SKIPPED_SPAM
    elif parsed.is_wanted:
        skipped = IngestAction.SKIPPED_WANTED
    if skipped is not None:
        if deactivate_existing:
            await repository.mark_deleted(SOURCE_NAME, [ext_id])
        return skipped

    listing = Listing(
        source=SOURCE_NAME,
        external_id=ext_id,
        url=message_url(chat_id, message_id, username),
        title=parsed.title,
        description=parsed.description,
        price_amount=parsed.price.amount if parsed.price else None,
        currency=parsed.price.currency if parsed.price else None,
        city=parsed.city,
        posted_at=_aware(posted_at),
    )
    raw = {"chat_id": chat_id, "message_id": message_id}
    await repository.upsert(listing, is_active=not parsed.is_sold, raw=raw)
    return IngestAction.STORED_INACTIVE if parsed.is_sold else IngestAction.STORED
