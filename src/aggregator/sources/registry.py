"""Builds the sources enabled by configuration. Adding a source = one builder function here."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aggregator.cache import InMemoryTTLCache
from aggregator.config import Settings
from aggregator.db.repositories import ListingRepository
from aggregator.domain.models import Listing
from aggregator.sources.base import ListingSource
from aggregator.sources.bazaraki.client import BazarakiClient
from aggregator.sources.bazaraki.source import BazarakiSource
from aggregator.sources.facebook.source import FacebookMarketplaceSource
from aggregator.sources.telegram.source import TelegramSource

log = structlog.get_logger()

SessionFactory = async_sessionmaker[AsyncSession]


@dataclass
class SourceRegistry:
    sources: list[ListingSource] = field(default_factory=list)
    _closers: list[Callable[[], Awaitable[None]]] = field(default_factory=list)

    @property
    def names(self) -> list[str]:
        return [source.name for source in self.sources]

    async def aclose(self) -> None:
        for close in self._closers:
            await close()


def build_registry(settings: Settings, session_factory: SessionFactory | None) -> SourceRegistry:
    registry = SourceRegistry()
    for name in dict.fromkeys(settings.enabled_sources):  # ordered, deduplicated
        if name == "bazaraki":
            client = BazarakiClient(
                user_agent=settings.bazaraki_user_agent,
                min_interval_seconds=settings.bazaraki_min_request_interval_seconds,
            )
            cache: InMemoryTTLCache[list[Listing]] = InMemoryTTLCache(max_entries=256)
            registry.sources.append(
                BazarakiSource(
                    client,
                    cache,
                    cache_ttl_seconds=settings.bazaraki_cache_ttl_seconds,
                    max_pages=settings.bazaraki_max_pages,
                    max_terms=settings.bazaraki_max_terms,
                )
            )
            registry._closers.append(client.aclose)
        elif name == "telegram":
            if session_factory is None:
                log.warning("registry.source_skipped", source=name, reason="no database")
                continue
            registry.sources.append(
                TelegramSource(
                    ListingRepository(session_factory),
                    max_age_days=settings.listing_max_age_days,
                )
            )
        elif name == "facebook":
            continue  # gated by ENABLE_FACEBOOK_MARKETPLACE below
        else:
            log.warning("registry.unknown_source", source=name)

    if settings.enable_facebook_marketplace:
        registry.sources.append(FacebookMarketplaceSource())
    return registry
