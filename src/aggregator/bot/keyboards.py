"""Inline keyboards. Callback data (all < 64 bytes): `lang:<code>`, `city:<value>`, `pg:<page>`,
`f:menu|back|reset|reset:menu|sort:<order>|src:<name|all>|price:<min|max>`."""

from __future__ import annotations

from collections.abc import Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from aggregator.bot.formatting import format_money, option_label, source_label
from aggregator.bot.i18n import Texts
from aggregator.domain.cities import SELECTABLE_CITIES
from aggregator.domain.models import Filters, SortOrder
from aggregator.search.category_choice import CategoryOption

LANG_PREFIX = "lang:"
CITY_PREFIX = "city:"
PAGE_PREFIX = "pg:"
FILTER_PREFIX = "f:"
CATEGORY_PREFIX = "c:"
ANY_CATEGORY = "any"
NOOP = "noop"

F_MENU = "f:menu"
F_BACK = "f:back"
F_RESET = "f:reset"  # from the results screen: stay on results
F_RESET_MENU = "f:reset:menu"  # from the filters menu: stay in the menu
F_UNUSUAL = "f:odd"  # toggle showing unusually priced listings
F_AREA = "f:area"  # open the area picker; "f:area:<n>" picks the n-th, "f:area:all" clears
ALL_SOURCES = "all"

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


def _pager_row(t: Texts, page: int, pages: int) -> list[InlineKeyboardButton]:
    """Prev / "2/5" / Next. Absolute page numbers, so a double tap never skips a page."""
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
    return row


def results_keyboard(
    t: Texts, page: int, pages: int, *, filters_active: bool
) -> InlineKeyboardMarkup:
    """Pager (when there is more than one page) plus Filters and, if any are set, Reset."""
    rows: list[list[InlineKeyboardButton]] = []
    if pages > 1:
        rows.append(_pager_row(t, page, pages))
    actions = [InlineKeyboardButton(text=t("btn_filters"), callback_data=F_MENU)]
    if filters_active:
        actions.append(InlineKeyboardButton(text=t("btn_reset_filters"), callback_data=F_RESET))
    rows.append(actions)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _mark(label: str, active: bool) -> str:
    return f"✓ {label}" if active else label


def filters_keyboard(t: Texts, filters: Filters, sources: Sequence[str]) -> InlineKeyboardMarkup:
    sort_row = [
        InlineKeyboardButton(
            text=_mark(t(f"sort.{order.value}"), filters.sort is order),
            callback_data=f"{FILTER_PREFIX}sort:{order.value}",
        )
        for order in SortOrder
    ]
    source_row = [
        InlineKeyboardButton(
            text=_mark(t("source.all"), filters.source is None),
            callback_data=f"{FILTER_PREFIX}src:{ALL_SOURCES}",
        ),
        *(
            InlineKeyboardButton(
                text=_mark(source_label(name), filters.source == name),
                callback_data=f"{FILTER_PREFIX}src:{name}",
            )
            for name in sources
        ),
    ]
    min_label = t("btn_min_price")
    max_label = t("btn_max_price")
    if filters.min_price is not None:
        min_label += f": {format_money(filters.min_price)}"
    if filters.max_price is not None:
        max_label += f": {format_money(filters.max_price)}"
    price_row = [
        InlineKeyboardButton(text=min_label, callback_data=f"{FILTER_PREFIX}price:min"),
        InlineKeyboardButton(text=max_label, callback_data=f"{FILTER_PREFIX}price:max"),
    ]
    area_label = t("btn_area") + (f": {filters.area}" if filters.area else "")
    area_row = [InlineKeyboardButton(text=area_label, callback_data=F_AREA)]
    unusual_state = t("unusual.shown" if filters.show_unusual_prices else "unusual.hidden")
    unusual_row = [
        InlineKeyboardButton(text=t("filter_unusual", value=unusual_state), callback_data=F_UNUSUAL)
    ]
    last_row = [InlineKeyboardButton(text=t("btn_back"), callback_data=F_BACK)]
    if not filters.is_default:
        last_row.insert(
            0, InlineKeyboardButton(text=t("btn_reset_filters"), callback_data=F_RESET_MENU)
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[sort_row, source_row, price_row, area_row, unusual_row, last_row]
    )


def category_keyboard(
    t: Texts, options: Sequence[CategoryOption], prefix: str | None
) -> InlineKeyboardMarkup:
    """One button per option (`c:<index>`, indexes into the stored pending options), then
    "Any category" (`c:any`). Indexes, not paths, keep callback data short and unforgeable."""
    rows = [
        [
            InlineKeyboardButton(
                text=option_label(t, option, prefix), callback_data=f"{CATEGORY_PREFIX}{i}"
            )
        ]
        for i, option in enumerate(options)
    ]
    rows.append(
        [
            InlineKeyboardButton(
                text=t("btn_any_category"), callback_data=f"{CATEGORY_PREFIX}{ANY_CATEGORY}"
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def area_keyboard(t: Texts, areas: Sequence[tuple[str, int]]) -> InlineKeyboardMarkup:
    """One button per area (`f:area:<index>`), then "All areas" and Back to the filters menu."""
    rows = [
        [
            InlineKeyboardButton(
                text=t("area_option", area=name, count=count),
                callback_data=f"{F_AREA}:{index}",
            )
        ]
        for index, (name, count) in enumerate(areas)
    ]
    rows.append(
        [
            InlineKeyboardButton(text=t("btn_all_areas"), callback_data=f"{F_AREA}:{ALL_SOURCES}"),
            InlineKeyboardButton(text=t("btn_cancel"), callback_data=F_MENU),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def price_prompt_keyboard(t: Texts) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t("btn_cancel"), callback_data=F_MENU)]]
    )
