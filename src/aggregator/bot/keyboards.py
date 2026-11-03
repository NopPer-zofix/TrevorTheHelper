"""Inline keyboards. Callback data: `lang:<code>`, `city:<value>`, `pg:<page>` (all < 64 bytes)."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from aggregator.bot.i18n import Texts
from aggregator.domain.cities import SELECTABLE_CITIES

LANG_PREFIX = "lang:"
CITY_PREFIX = "city:"
PAGE_PREFIX = "pg:"
NOOP = "noop"

LANGUAGE_BUTTONS = (("English", "en"), ("Русский", "ru"))


def language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=label, callback_data=f"{LANG_PREFIX}{code}")
                for label, code in LANGUAGE_BUTTONS
            ]
        ]
    )


def city_keyboard(t: Texts) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text=t.city(c.value), callback_data=f"{CITY_PREFIX}{c.value}")
        for c in SELECTABLE_CITIES
    ]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def pager_keyboard(t: Texts, page: int, pages: int) -> InlineKeyboardMarkup | None:
    """Prev / "2/5" / Next. Absolute page numbers, so a double tap never skips a page."""
    if pages <= 1:
        return None
    row: list[InlineKeyboardButton] = []
    if page > 0:
        row.append(
            InlineKeyboardButton(text=t("btn_prev"), callback_data=f"{PAGE_PREFIX}{page - 1}")
        )
    row.append(
        InlineKeyboardButton(text=t("btn_page", page=page + 1, pages=pages), callback_data=NOOP)
    )
    if page < pages - 1:
        row.append(
            InlineKeyboardButton(text=t("btn_next"), callback_data=f"{PAGE_PREFIX}{page + 1}")
        )
    return InlineKeyboardMarkup(inline_keyboard=[row])
