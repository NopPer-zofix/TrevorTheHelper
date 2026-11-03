from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from aggregator.domain.cities import City
from aggregator.domain.models import Listing
from aggregator.sources.telegram.indexer import Group, Indexer, normalize_group
from aggregator.sources.telegram.ingest import (
    IngestAction,
    external_id,
    ingest_message,
    message_url,
)

POSTED = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
MARKED_CHAT_ID = -1000000000555  # Telethon's marked id for the supergroup with real id 555


class FakeRepo:
    def __init__(self) -> None:
        self.upserts: list[tuple[Listing, bool, dict[str, Any] | None]] = []
        self.deleted: list[list[str]] = []

    async def upsert(
        self, listing: Listing, *, is_active: bool = True, raw: dict[str, Any] | None = None
    ) -> None:
        self.upserts.append((listing, is_active, raw))

    async def mark_deleted(self, source: str, external_ids: list[str]) -> int:
        self.deleted.append(list(external_ids))
        return len(external_ids)


async def ingest(repo: FakeRepo, text: str | None, **kwargs: Any) -> IngestAction:
    params: dict[str, Any] = {
        "chat_id": 555,
        "message_id": 7,
        "username": "baraholka_kipr",
        "text": text,
        "posted_at": POSTED,
    }
    params.update(kwargs)
    return await ingest_message(repo, **params)


def test_ids_and_urls() -> None:
    assert external_id(555, 7) == "555:7"
    assert message_url(555, 7, "baraholka_kipr") == "https://t.me/baraholka_kipr/7"
    assert message_url(555, 7, None) == "https://t.me/c/555/7"


async def test_sale_post_is_stored_active() -> None:
    repo = FakeRepo()
    action = await ingest(repo, "Велосипед Trek FX 2\nЦена 250€, Лимассол")

    assert action is IngestAction.STORED
    listing, is_active, raw = repo.upserts[0]
    assert is_active
    assert listing.external_id == "555:7"
    assert listing.url == "https://t.me/baraholka_kipr/7"
    assert listing.title == "Велосипед Trek FX 2"
    assert listing.price_amount == Decimal("250")
    assert listing.currency == "EUR"
    assert listing.city is City.LIMASSOL
    assert raw == {"chat_id": 555, "message_id": 7}


async def test_sold_post_is_stored_inactive() -> None:
    repo = FakeRepo()
    action = await ingest(repo, "ПРОДАНО Велосипед Trek 250€")

    assert action is IngestAction.STORED_INACTIVE
    assert repo.upserts[0][1] is False


async def test_wanted_post_is_skipped_and_existing_row_deactivated() -> None:
    repo = FakeRepo()
    action = await ingest(repo, "Куплю велосипед до 200€")

    assert action is IngestAction.SKIPPED_WANTED
    assert repo.upserts == []
    assert repo.deleted == [["555:7"]]


@pytest.mark.parametrize("text", [None, "", "   ", "#tag 🔥"])
async def test_empty_post_is_skipped(text: str | None) -> None:
    repo = FakeRepo()
    assert await ingest(repo, text) is IngestAction.SKIPPED_EMPTY
    assert repo.upserts == []


async def test_backfill_does_not_touch_the_db_for_skipped_posts() -> None:
    repo = FakeRepo()
    await ingest(repo, "Куплю диван", deactivate_existing=False)
    assert repo.deleted == []


async def test_naive_datetime_is_made_aware() -> None:
    repo = FakeRepo()
    await ingest(repo, "Sofa 100 eur", posted_at=datetime(2026, 11, 1, 12, 0))
    assert repo.upserts[0][0].posted_at.tzinfo is not None


@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        ("https://t.me/baraholka_kipr", "baraholka_kipr"),
        ("http://t.me/baraholka_kipr/", "baraholka_kipr"),
        ("t.me/baraholka_kipr?start=1", "baraholka_kipr"),
        ("@baraholka_kipr", "baraholka_kipr"),
        ("baraholka_kipr", "baraholka_kipr"),
        ("https://t.me/+AbCdEfGh123", None),
        ("https://t.me/joinchat/AbCdEf", None),
        ("https://t.me/c/123456/7", None),
        ("not a group!", None),
        ("", None),
    ],
)
def test_normalize_group(ref: str, expected: str | None) -> None:
    assert normalize_group(ref) == expected


def make_indexer(repo: Any) -> Indexer:
    indexer = Indexer(SimpleNamespace(), repo, backfill_days=30, max_age_days=30)  # type: ignore[arg-type]
    indexer._groups[555] = Group(chat_id=555, username="baraholka_kipr", title="Baraholka")
    return indexer


def message_event(text: str, message_id: int = 7) -> Any:
    message = SimpleNamespace(id=message_id, message=text, date=POSTED)
    return SimpleNamespace(chat_id=MARKED_CHAT_ID, message=message)


async def test_live_message_handler_resolves_marked_chat_id() -> None:
    repo = FakeRepo()
    await make_indexer(repo)._on_message(message_event("Desk 80 eur, Paphos"))

    listing = repo.upserts[0][0]
    assert listing.external_id == "555:7"
    assert listing.url == "https://t.me/baraholka_kipr/7"


async def test_edit_into_wanted_post_deactivates_the_listing() -> None:
    repo = FakeRepo()
    await make_indexer(repo)._on_message(message_event("Wanted: desk"))
    assert repo.deleted == [["555:7"]]


async def test_handler_errors_do_not_propagate() -> None:
    class Boom(FakeRepo):
        async def upsert(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError("db down")

    await make_indexer(Boom())._on_message(message_event("Desk 80 eur"))  # must not raise


async def test_deleted_handler_marks_all_ids() -> None:
    repo = FakeRepo()
    event = SimpleNamespace(chat_id=MARKED_CHAT_ID, deleted_ids=[7, 8])
    indexer = make_indexer(repo)
    indexer._repository = repo  # type: ignore[assignment]

    await indexer._on_deleted(event)
    assert repo.deleted == [["555:7", "555:8"]]


async def test_deleted_handler_ignores_events_without_chat() -> None:
    repo = FakeRepo()
    await make_indexer(repo)._on_deleted(SimpleNamespace(chat_id=None, deleted_ids=[7]))
    assert repo.deleted == []
