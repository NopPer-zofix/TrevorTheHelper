"""TTL cache behind an interface: in-memory now, Redis-ready later."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Protocol


class Cache[V](Protocol):
    async def get(self, key: str) -> V | None: ...

    async def set(self, key: str, value: V, ttl_seconds: float) -> None: ...

    async def delete(self, key: str) -> None: ...


class InMemoryTTLCache[V]:
    """Process-local cache with per-entry expiry and a soft size bound."""

    def __init__(
        self,
        max_entries: int = 1024,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._data: dict[str, tuple[float, V]] = {}
        self._max_entries = max_entries
        self._clock = clock

    async def get(self, key: str) -> V | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at <= self._clock():
            del self._data[key]
            return None
        return value

    async def set(self, key: str, value: V, ttl_seconds: float) -> None:
        if len(self._data) >= self._max_entries and key not in self._data:
            self._evict()
        self._data[key] = (self._clock() + ttl_seconds, value)

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    def _evict(self) -> None:
        now = self._clock()
        expired = [k for k, (exp, _) in self._data.items() if exp <= now]
        for key in expired:
            del self._data[key]
        if len(self._data) >= self._max_entries:
            # Still full: drop the entry closest to expiry.
            oldest = min(self._data, key=lambda k: self._data[k][0])
            del self._data[oldest]
