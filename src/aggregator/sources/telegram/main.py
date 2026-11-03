"""`indexer` process entrypoint. Milestone 1: boots config and logging only."""

from __future__ import annotations

import asyncio

import structlog

from aggregator.config import get_settings
from aggregator.logging import configure_logging


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.log_json)
    log = structlog.get_logger()
    log.info("indexer.started", groups=settings.telegram_groups)
    await asyncio.Event().wait()  # replaced by the Telethon indexer in milestone 4


def run() -> None:
    asyncio.run(main())
