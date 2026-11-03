"""`bot` process entrypoint. Milestone 1: boots config, logging and the health endpoint only."""

from __future__ import annotations

import asyncio

import structlog

from aggregator.config import get_settings
from aggregator.health import start_health_server
from aggregator.logging import configure_logging


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.log_json)
    log = structlog.get_logger()
    runner = await start_health_server(settings.health_port)
    log.info("bot.started", mode=settings.bot_mode, private=settings.is_private_mode)
    try:
        await asyncio.Event().wait()  # replaced by the aiogram dispatcher in milestone 6
    finally:
        await runner.cleanup()


def run() -> None:
    asyncio.run(main())
