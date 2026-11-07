"""A search waiting for the user's answer to a category question ("rent or buy?")."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from aggregator.cache import Cache
from aggregator.domain.models import ExpandedQuery


class PendingSearch(BaseModel):
    text: str  # the user's cleaned search text
    query: ExpandedQuery  # already expanded, so answering does not expand it again
    counts: dict[str, int]  # the category sample the questions are based on
    intent: Literal["rent", "sale"] | None = None  # when the text said so
    prefix: str | None = None  # the part of the category path settled so far
    options: list[str] = Field(default_factory=list)  # paths offered, in button order


class PendingStore:
    """At most one pending question per user: a new search replaces it."""

    def __init__(self, cache: Cache[PendingSearch], ttl_seconds: float) -> None:
        self._cache = cache
        self._ttl = ttl_seconds

    @staticmethod
    def _key(user_id: int) -> str:
        return f"pending-search:{user_id}"

    async def get(self, user_id: int) -> PendingSearch | None:
        return await self._cache.get(self._key(user_id))

    async def save(self, user_id: int, pending: PendingSearch) -> None:
        await self._cache.set(self._key(user_id), pending, self._ttl)

    async def clear(self, user_id: int) -> None:
        await self._cache.delete(self._key(user_id))
