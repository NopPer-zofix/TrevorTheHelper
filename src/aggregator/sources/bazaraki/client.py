"""Polite HTTP access to Bazaraki: serialized requests with a minimum interval, retries with
backoff on transient failures, and a hard stop (no workarounds) when the site refuses us."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping

import httpx
import structlog

from aggregator.sources.base import SourceError
from aggregator.sources.bazaraki.selectors import BASE_URL

log = structlog.get_logger()

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_MAX_RETRY_AFTER_SECONDS = 30.0


class BazarakiClient:
    def __init__(
        self,
        *,
        user_agent: str,
        min_interval_seconds: float = 1.0,
        max_attempts: int = 3,
        backoff_base_seconds: float = 1.0,
        timeout_seconds: float = 10.0,
        http: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._http = http or httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": user_agent, "Accept-Language": "en"},
        )
        self._min_interval = min_interval_seconds
        self._max_attempts = max_attempts
        self._backoff_base = backoff_base_seconds
        self._sleep = sleep
        self._clock = clock
        self._lock = asyncio.Lock()
        self._last_request_at: float | None = None

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _throttle(self) -> None:
        if self._last_request_at is not None:
            wait = self._min_interval - (self._clock() - self._last_request_at)
            if wait > 0:
                await self._sleep(wait)
        self._last_request_at = self._clock()

    async def get_html(self, path: str, params: Mapping[str, str | int] | None = None) -> str:
        last_problem = "unknown error"
        for attempt in range(1, self._max_attempts + 1):
            async with self._lock:  # one request at a time, spaced out
                await self._throttle()
                try:
                    response = await self._http.get(path, params=params)
                except httpx.TransportError as exc:
                    last_problem = f"{type(exc).__name__}: {exc}"
                    retry_after = None
                else:
                    if response.status_code == 200:
                        return response.text
                    if response.status_code not in _RETRYABLE_STATUS:
                        # 403/404/...: not welcome, or a wrong URL. Never work around it.
                        raise SourceError(f"bazaraki returned HTTP {response.status_code}")
                    last_problem = f"HTTP {response.status_code}"
                    retry_after = _retry_after(response)

            if attempt < self._max_attempts:
                delay = (
                    retry_after
                    if retry_after is not None
                    else self._backoff_base * 2 ** (attempt - 1)
                )
                log.warning("bazaraki.retry", attempt=attempt, problem=last_problem, delay=delay)
                await self._sleep(delay)
        raise SourceError(
            f"bazaraki unavailable after {self._max_attempts} attempts ({last_problem})"
        )


def _retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return min(max(float(raw), 0.0), _MAX_RETRY_AFTER_SECONDS)
    except ValueError:
        return None
