"""Per-user state of the last search: lets the user page and re-filter without re-fetching."""

from __future__ import annotations

from pydantic import BaseModel, Field

from aggregator.cache import Cache
from aggregator.domain.models import Filters
from aggregator.search.models import SearchOutcome


class SearchSession(BaseModel):
    outcome: SearchOutcome
    filters: Filters = Field(default_factory=Filters)
    page: int = 0


class SessionStore:
    def __init__(self, cache: Cache[SearchSession], ttl_seconds: float) -> None:
        self._cache = cache
        self._ttl = ttl_seconds

    @staticmethod
    def _key(user_id: int) -> str:
        return f"search-session:{user_id}"

    async def get(self, user_id: int) -> SearchSession | None:
        return await self._cache.get(self._key(user_id))

    async def save(self, user_id: int, session: SearchSession) -> None:
        await self._cache.set(self._key(user_id), session, self._ttl)
