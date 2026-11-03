"""`QueryExpander`: cache -> LLM -> rule-based fallback. Never raises for a non-empty query."""

from __future__ import annotations

from typing import Protocol

import structlog

from aggregator.cache import Cache, InMemoryTTLCache
from aggregator.config import Settings
from aggregator.domain.models import ExpandedQuery
from aggregator.query.fallback import expand_with_rules
from aggregator.query.llm import AnthropicExpander, LLMExpansionError
from aggregator.query.normalize import normalize_input
from aggregator.query.store import ExpansionStore

log = structlog.get_logger(__name__)

_MEMORY_TTL_SECONDS = 3600.0


class LLMExpander(Protocol):
    async def expand(self, text: str) -> ExpandedQuery: ...


class QueryExpander:
    def __init__(
        self,
        *,
        llm: LLMExpander | None = None,
        store: ExpansionStore | None = None,
        memory: Cache[ExpandedQuery] | None = None,
    ) -> None:
        self._llm = llm
        self._store = store
        self._memory: Cache[ExpandedQuery] = memory or InMemoryTTLCache(max_entries=512)

    async def expand(self, text: str) -> ExpandedQuery:
        key = normalize_input(text)
        if not key:
            raise ValueError("query is empty after normalisation")

        cached = await self._memory.get(key)
        if cached is not None:
            return cached.model_copy(update={"original": text})

        stored = await self._from_store(key, text)
        if stored is not None:
            await self._memory.set(key, stored, _MEMORY_TTL_SECONDS)
            return stored

        if self._llm is not None:
            try:
                expansion = await self._llm.expand(text)
            except LLMExpansionError as exc:
                log.warning("query_expansion_fallback", reason=str(exc), query=key)
            else:
                await self._remember(key, expansion)
                return expansion

        # Fallback results are not cached: once the API is back, the next search upgrades.
        return expand_with_rules(text)

    async def _from_store(self, key: str, original: str) -> ExpandedQuery | None:
        if self._store is None:
            return None
        try:
            return await self._store.get(key, original=original)
        except Exception:  # a broken cache must never break a search
            log.warning("query_expansion_store_read_failed", exc_info=True)
            return None

    async def _remember(self, key: str, expansion: ExpandedQuery) -> None:
        await self._memory.set(key, expansion, _MEMORY_TTL_SECONDS)
        if self._store is None:
            return
        try:
            await self._store.put(key, expansion)
        except Exception:
            log.warning("query_expansion_store_write_failed", exc_info=True)


def build_query_expander(settings: Settings, store: ExpansionStore | None = None) -> QueryExpander:
    """Wire the expander from settings. Without an API key it is fallback-only."""
    llm: AnthropicExpander | None = None
    if settings.anthropic_api_key:
        llm = AnthropicExpander(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
            timeout_seconds=settings.anthropic_timeout_seconds,
        )
    else:
        log.info("query_expansion_llm_disabled", reason="ANTHROPIC_API_KEY not set")
    return QueryExpander(llm=llm, store=store)
