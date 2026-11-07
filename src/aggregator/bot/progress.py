"""The single "Searching…" message: edited as sources respond, then replaced by the results."""

from __future__ import annotations

from typing import Any

import structlog
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardMarkup, Message

from aggregator.bot.formatting import format_progress
from aggregator.bot.i18n import Texts
from aggregator.domain.cities import City
from aggregator.search.models import SourceStatus

log = structlog.get_logger()


class ProgressMessage:
    def __init__(
        self,
        origin: Message,
        t: Texts,
        query: str,
        city: City,
        source_names: list[str],
        existing: Message | None = None,
    ) -> None:
        self._origin = origin
        self._t = t
        self._query = query
        self._city = city
        self._source_names = source_names
        self._done: dict[str, SourceStatus] = {}
        # `existing`: reuse a message already on screen (e.g. the category question) instead of
        # sending a new one.
        self._message: Message | None = existing

    def _text(self) -> str:
        return format_progress(self._t, self._query, self._city, self._source_names, self._done)

    async def start(self) -> None:
        if self._message is not None:
            try:
                await self._message.edit_text(self._text(), reply_markup=None)
            except TelegramAPIError:
                log.debug("progress.reuse_failed", exc_info=True)
            return
        self._message = await self._origin.answer(self._text())

    async def on_status(self, status: SourceStatus) -> None:
        self._done[status.name] = status
        if self._message is None:
            return
        try:
            await self._message.edit_text(self._text())
        except TelegramAPIError:  # "not modified", flood control...: progress is cosmetic
            log.debug("progress.edit_skipped", exc_info=True)

    async def finish(self, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
        """Replace the progress text with the final text (falls back to a new message)."""
        kwargs: dict[str, Any] = {"reply_markup": markup}
        if self._message is not None:
            try:
                await self._message.edit_text(text, **kwargs)
            except TelegramAPIError:
                log.warning("progress.final_edit_failed", exc_info=True)
            else:
                return
        await self._origin.answer(text, **kwargs)
