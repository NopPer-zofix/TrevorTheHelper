"""`bot` process entrypoint: wires config, DB, sources, services and runs the dispatcher."""

from __future__ import annotations

import asyncio
import sys

import structlog
from sqlalchemy import text

from aggregator.bot.context import Services
from aggregator.bot.runner import build_dispatcher, create_bot, run_polling, run_webhook
from aggregator.cache import InMemoryTTLCache
from aggregator.config import get_settings
from aggregator.db.session import create_engine, create_session_factory
from aggregator.health import start_health_server
from aggregator.logging import configure_logging
from aggregator.query.service import build_query_expander
from aggregator.query.store import DbExpansionStore
from aggregator.search.orchestrator import SearchOrchestrator
from aggregator.services.pending import PendingSearch, PendingStore
from aggregator.services.search_service import DbSearchLogStore, SearchService
from aggregator.services.sessions import SearchSession, SessionStore
from aggregator.services.users import DbUserStore, UserService
from aggregator.sources.registry import build_registry


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.log_json)
    log = structlog.get_logger()

    if not settings.bot_token:
        log.error("bot.no_token", hint="Set BOT_TOKEN (from @BotFather) in .env")
        sys.exit(1)

    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    registry = build_registry(settings, session_factory)
    expander = build_query_expander(settings, DbExpansionStore(session_factory))
    orchestrator = SearchOrchestrator(
        registry.sources,
        source_timeout_seconds=settings.source_timeout_seconds,
        min_relevance=settings.relevance_min_score,
    )
    services = Services(
        users=UserService(DbUserStore(session_factory)),
        search=SearchService(
            expander,
            orchestrator,
            DbSearchLogStore(session_factory),
            best_deal_ratio=settings.best_deal_ratio,
            max_query_length=settings.max_query_length,
            explorers=registry.explorers,
            explore_timeout_seconds=settings.source_timeout_seconds,
        ),
        sessions=SessionStore(
            InMemoryTTLCache[SearchSession](max_entries=2048),
            settings.result_session_ttl_seconds,
        ),
        pending=PendingStore(
            InMemoryTTLCache[PendingSearch](max_entries=2048),
            settings.pending_question_ttl_seconds,
        ),
        source_names=registry.names,
        show_best_deals=settings.show_best_deals,
    )

    async def db_healthy() -> bool:
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception:
            return False
        return True

    health = await start_health_server(settings.health_port, db_healthy)
    bot = create_bot(settings.bot_token)
    dispatcher = build_dispatcher(services, settings)
    log.info(
        "bot.started",
        mode=settings.bot_mode,
        private=settings.is_private_mode,
        sources=registry.names,
    )
    try:
        if settings.bot_mode == "webhook":
            await run_webhook(bot, dispatcher, settings)
        else:
            await run_polling(bot, dispatcher)
    finally:
        await bot.session.close()
        await registry.aclose()
        await health.cleanup()
        await engine.dispose()


def run() -> None:
    asyncio.run(main())
