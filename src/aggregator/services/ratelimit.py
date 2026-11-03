"""Per-user sliding-window rate limiter (in-memory; swap for Redis when scaling out)."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable


class SlidingWindowRateLimiter:
    def __init__(
        self,
        limit: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = limit
        self._window = window_seconds
        self._clock = clock
        self._hits: dict[int, deque[float]] = {}

    def hit(self, key: int) -> float | None:
        """Record a request. Returns None if allowed, else seconds until a slot frees up."""
        now = self._clock()
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= now - self._window:
            hits.popleft()
        if len(hits) >= self._limit:
            return max(hits[0] + self._window - now, 0.0)
        hits.append(now)
        if len(self._hits) > 10_000:  # bound memory: forget idle users
            self._prune(now)
        return None

    def _prune(self, now: float) -> None:
        for key in [k for k, v in self._hits.items() if not v or v[-1] <= now - self._window]:
            del self._hits[key]
