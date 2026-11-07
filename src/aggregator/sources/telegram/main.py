"""`indexer` process entrypoint: Telethon reader that keeps the listings table fresh."""

from __future__ import annotations

import asyncio
import sys

import structlog
from telethon import TelegramClient

from aggregator.config import get_settings
from aggregator.db.repositories import ListingRepository
from aggregator.db.session import create_engine, create_session_factory
from aggregator.health import HealthCheck, start_health_server
from aggregator.logging import configure_logging
from aggregator.sources.telegram.client import build_client
from aggregator.sources.telegram.indexer import Indexer


async def main() -> int:
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.log_json)
    log = structlog.get_logger()

    if not settings.telegram_groups:
        log.error("indexer.no_groups", hint="set TELEGRAM_GROUPS (public group @usernames)")
        return 1
    try:
        client = build_client(settings)
    except RuntimeError as exc:
        log.error("indexer.not_configured", error=str(exc))
        return 1

    await client.connect()
    if not await client.is_user_authorized():
        log.error(
            "indexer.not_authorized",
            hint="run `make telegram-login` once to create the reader session",
        )
        await client.disconnect()
        return 1

    engine = create_engine(settings.database_url)
    indexer = Indexer(
        client,
        ListingRepository(create_session_factory(engine)),
        backfill_days=settings.telegram_backfill_days,
        max_age_days=settings.listing_max_age_days,
    )
    health = await start_health_server(settings.health_port, check=_connected(client))
    try:
        groups = await indexer.resolve_groups(settings.telegram_groups)
        if not groups:
            log.error("indexer.no_groups_resolved")
            return 1
        indexer.register_handlers()  # before backfill, so nothing posted meanwhile is missed
        log.info("indexer.started", groups=[g.username for g in groups])
        await indexer.purge_spam()  # hide spam stored before the filter existed
        for group in groups:
            await indexer.backfill(group)
        retention = asyncio.create_task(indexer.run_retention())
        try:
            await client.run_until_disconnected()
        finally:
            retention.cancel()
    finally:
        await health.cleanup()
        await client.disconnect()
        await engine.dispose()
    return 0


def _connected(client: TelegramClient) -> HealthCheck:
    async def check() -> bool:
        return bool(client.is_connected())

    return check


def run() -> None:
    sys.exit(asyncio.run(main()))
