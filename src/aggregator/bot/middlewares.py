"""Private-mode allowlist and per-user rate limiting."""

from __future__ import annotations

import math
from collections.abc import Awaitable, Callable, Collection
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, User

from aggregator.bot.i18n import Texts
from aggregator.services.ratelimit import SlidingWindowRateLimiter
from aggregator.services.users import guess_language

Handler = Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]]


async def _reply(event: TelegramObject, text: str) -> None:
    if isinstance(event, Message):
        await event.answer(text)
    elif isinstance(event, CallbackQuery):
        await event.answer(text, show_alert=True)


def _texts_for(user: User | None) -> Texts:
    return Texts(guess_language(user.language_code if user else None))


class AccessMiddleware(BaseMiddleware):
    """Private mode: only `allowed_ids` may use the bot. An empty list means public."""

    def __init__(self, allowed_ids: Collection[int]) -> None:
        self._allowed = frozenset(allowed_ids)

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        if not self._allowed:
            return await handler(event, data)
        user: User | None = data.get("event_from_user")
        if user is not None and user.id in self._allowed:
            return await handler(event, data)
        await _reply(event, _texts_for(user)("not_allowed"))
        return None


class RateLimitMiddleware(BaseMiddleware):
    """Applied to messages only (a message can trigger a search); paging taps are cheap."""

    def __init__(self, limiter: SlidingWindowRateLimiter) -> None:
        self._limiter = limiter

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        user: User | None = data.get("event_from_user")
        if user is None:
            return await handler(event, data)
        retry_after = self._limiter.hit(user.id)
        if retry_after is None:
            return await handler(event, data)
        await _reply(
            event, _texts_for(user)("rate_limited", seconds=max(1, math.ceil(retry_after)))
        )
        return None
