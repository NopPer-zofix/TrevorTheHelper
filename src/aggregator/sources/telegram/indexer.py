"""Telethon indexer: backfills recent history and follows new/edited/deleted group messages.

Strictly read-only. It never writes to Telegram (tests/test_telegram_readonly.py enforces this).
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from telethon import TelegramClient, events, utils

from aggregator.db.repositories import ListingRepository
from aggregator.sources.telegram.ingest import SOURCE_NAME, external_id, ingest_message

log = structlog.get_logger()

BACKFILL_WAIT_SECONDS = 1.0  # pause between history pages; stays far from FloodWait
RETENTION_INTERVAL_SECONDS = 6 * 3600

_USERNAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,31}$")
_LINK = re.compile(r"^(?:https?://)?(?:t|telegram)\.me/(?P<rest>.+)$", re.IGNORECASE)


def normalize_group(ref: str) -> str | None:
    """ "https://t.me/foo", "@foo" or "foo" -> "foo". Invite links and junk -> None."""
    value = ref.strip()
    link = _LINK.match(value)
    if link:
        rest = link.group("rest").split("?")[0].strip("/")
        first = rest.split("/")[0]
        if first.startswith("+") or first.lower() in {"joinchat", "c"}:
            return None  # invite links / private-group links need a join we never perform
        value = first
    value = value.lstrip("@")
    return value if _USERNAME.match(value) else None


@dataclass(frozen=True)
class Group:
    chat_id: int  # real (unmarked) id
    username: str | None
    title: str


class Indexer:
    def __init__(
        self,
        client: TelegramClient,
        repository: ListingRepository,
        *,
        backfill_days: int,
        max_age_days: int,
    ) -> None:
        self._client = client
        self._repository = repository
        self._backfill_days = backfill_days
        self._max_age_days = max_age_days
        self._groups: dict[int, Group] = {}

    async def resolve_groups(self, refs: list[str]) -> list[Group]:
        for ref in refs:
            username = normalize_group(ref)
            if username is None:
                log.warning("indexer.group_unsupported", group=ref, hint="use a public @username")
                continue
            try:
                entity: Any = await self._client.get_entity(username)
            except Exception as exc:
                log.warning("indexer.group_unresolved", group=username, error=str(exc))
                continue
            group = Group(
                chat_id=int(entity.id),
                username=getattr(entity, "username", None) or username,
                title=getattr(entity, "title", username),
            )
            self._groups[group.chat_id] = group
            log.info("indexer.group_resolved", group=group.username, chat_id=group.chat_id)
        return list(self._groups.values())

    async def backfill(self, group: Group) -> int:
        """Index messages newer than the backfill window, newest first. Returns stored count."""
        cutoff = datetime.now(UTC) - timedelta(days=self._backfill_days)
        seen = stored = 0
        async for message in self._client.iter_messages(
            group.chat_id, wait_time=BACKFILL_WAIT_SECONDS
        ):
            if message.date < cutoff:
                break
            seen += 1
            action = await ingest_message(
                self._repository,
                chat_id=group.chat_id,
                message_id=message.id,
                username=group.username,
                text=message.message,
                posted_at=message.date,
                deactivate_existing=False,
            )
            stored += action.value.startswith("stored")
        log.info("indexer.backfill_done", group=group.username, seen=seen, stored=stored)
        return stored

    def register_handlers(self) -> None:
        chats = list(self._groups)
        self._client.add_event_handler(self._on_message, events.NewMessage(chats=chats))
        self._client.add_event_handler(self._on_message, events.MessageEdited(chats=chats))
        self._client.add_event_handler(self._on_deleted, events.MessageDeleted(chats=chats))

    async def _on_message(self, event: Any) -> None:
        try:
            chat_id, _ = utils.resolve_id(event.chat_id)
            group = self._groups.get(chat_id)
            message = event.message
            action = await ingest_message(
                self._repository,
                chat_id=chat_id,
                message_id=message.id,
                username=group.username if group else None,
                text=message.message,
                posted_at=message.date,
            )
            log.info("indexer.message", chat_id=chat_id, message_id=message.id, action=action.value)
        except Exception:
            log.exception("indexer.message_failed")  # one bad message must not stop the indexer

    async def _on_deleted(self, event: Any) -> None:
        try:
            if event.chat_id is None:
                return  # Telegram omits the chat for some deletions; nothing we can match
            chat_id, _ = utils.resolve_id(event.chat_id)
            ids = [external_id(chat_id, message_id) for message_id in event.deleted_ids]
            changed = await self._repository.mark_deleted(SOURCE_NAME, ids)
            log.info("indexer.deleted", chat_id=chat_id, requested=len(ids), deactivated=changed)
        except Exception:
            log.exception("indexer.delete_failed")

    async def run_retention(self) -> None:
        """Periodically hide listings older than the configured max age."""
        while True:
            cutoff = datetime.now(UTC) - timedelta(days=self._max_age_days)
            try:
                count = await self._repository.deactivate_older_than(SOURCE_NAME, cutoff)
                log.info("indexer.retention", deactivated=count)
            except Exception:
                log.exception("indexer.retention_failed")
            await asyncio.sleep(RETENTION_INTERVAL_SECONDS)
