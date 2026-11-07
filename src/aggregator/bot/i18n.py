"""Tiny i18n layer. Every user-facing string lives in the catalogs below (en, ru); handlers and
formatters only reference keys. Texts are HTML (Telegram parse mode); interpolated user data
must be escaped by the caller."""

from __future__ import annotations

from typing import Any

DEFAULT_LANGUAGE = "en"

EN: dict[str, str] = {
    # --- onboarding ---
    "choose_language": "Choose your language / Выберите язык",
    "language_set": "Language set to English.",
    "choose_city": "Which city should I search in?",
    "city_set": "City set to <b>{city}</b>. Now send me a product name, e.g. <b>iphone 13</b>.",
    "need_city": "Please choose a city first, then send your search again.",
    "help": (
        "<b>How it works</b>\n"
        "Send a product name (English or Russian), e.g. <i>iphone 13 128gb</i> or "
        "<i>велосипед горный</i>. I search Bazaraki and Telegram groups and show prices, "
        "best deals and listings.\n\n"
        "/city - change city\n/lang - change language\n/help - this message"
    ),
    # --- cities ---
    "city.nicosia": "Nicosia",
    "city.limassol": "Limassol",
    "city.larnaca": "Larnaca",
    "city.paphos": "Paphos",
    "city.famagusta": "Famagusta",
    "city.all": "All Cyprus",
    "city.unknown": "city not specified",
    # --- search progress ---
    "searching": "🔎 Searching for <b>{query}</b> in {city}…",
    "progress_done": "✅ {source}: {count}",
    "progress_failed": "⚠️ {source}: unavailable",
    "progress_waiting": "⏳ {source}…",
    # --- results ---
    "header": "🔎 <b>{query}</b> · {city}",
    "found_per_source": "Found {total}: {parts}",
    "source_unavailable": "{source} ⚠️",
    "partial_note": "⚠️ Couldn't get results from {sources}. Showing partial results.",
    "stats_title": "💶 <b>Prices (EUR)</b> — {sample} listings",
    "stats_outliers": ", {removed} outlier(s) excluded",
    "stats_line": "Average {average} · Median {median} · Min {minimum} · Max {maximum}",
    "stats_unreliable": "⚠️ Only {count} priced listing(s) — statistics are unreliable.",
    "stats_none": "No prices in these listings.",
    "stats_unpriced": "{count} listing(s) without a price are not counted.",
    "category_question": (
        "🗂 <b>What are you looking for?</b>\n"
        "“{query}” matches several kinds of listings. Pick one for cleaner results.{where}"
    ),
    "category_where": "\nIn: <b>{label}</b>",
    "category_option": "{label} ({count})",
    "btn_any_category": "🔎 Any category",
    "category_line": "🗂 Category: {category}",
    "category_expired": "That question has expired. Please send your search again.",
    "unusual_hidden": "🚫 {count} listing(s) with unusual prices hidden ({detail})",
    "unusual_low": "under {price}",
    "unusual_high": "over {price}",
    "unusual_mixed": (
        "ℹ️ Prices here vary a lot, so the statistics may not be representative. "
        "A more specific search will help."
    ),
    "unusual_shown": "⚠️ Unusually priced listings are marked ⚠️ and not counted in the statistics.",
    "filter_unusual": "Unusual prices: {value}",
    "unusual.hidden": "hidden",
    "unusual.shown": "shown",
    "summary_unusual": "unusual prices shown",
    "deals_title": "🏷 <b>Best deals</b>",
    "deal_line": '{index}. <a href="{url}">{title}</a> — {price} ({discount}% below median)',
    "page_title": "📄 <b>Listings</b> — page {page}/{pages}",
    "card_price_none": "price not listed",
    "card_posted": "posted {date}",
    "btn_prev": "◀ Prev",
    "btn_next": "Next ▶",
    # --- filters ---
    "btn_filters": "⚙️ Filters",
    "btn_reset_filters": "✖ Reset filters",
    "btn_back": "◀ Back to results",
    "btn_cancel": "Cancel",
    "btn_min_price": "Min price",
    "btn_max_price": "Max price",
    "filters_title": "⚙️ <b>Filters</b>",
    "filter_price": "Price: {value}",
    "filter_sort": "Sort: {value}",
    "filter_source": "Source: {value}",
    "price_any": "any",
    "price_range": "{low} – {high}",
    "price_from": "from {low}",
    "price_upto": "up to {high}",
    "sort.newest": "Newest",
    "sort.cheapest": "Cheapest",
    "sort.best_deal": "Best deal",
    "source.all": "All sources",
    "filters_matching": "{shown} of {total} listings match.",
    "filters_active": "🔧 <b>Filters:</b> {summary} — showing {shown} of {total}",
    "prompt_min_price": (
        "Send the <b>minimum</b> price in EUR, e.g. <i>150</i>. Send 0 to remove it."
    ),
    "prompt_max_price": (
        "Send the <b>maximum</b> price in EUR, e.g. <i>500</i>. Send 0 to remove it."
    ),
    "price_range_error": "The minimum can't be higher than the maximum. Try another number.",
    "no_match_filters": "No listings match your filters ({total} found before filtering).",
    "non_text": "I can only read text. Send me a product name to search for.",
    "btn_page": "{page}/{pages}",
    # --- problems ---
    "no_results": (
        "Nothing found for <b>{query}</b> in {city}.\n"
        "Try broader terms (fewer words, no specs), another spelling, or switch to "
        "<b>All Cyprus</b> with /city."
    ),
    "all_failed": "I couldn't reach any source right now. Please try again in a minute.",
    "invalid_empty": "Please send a product name to search for.",
    "invalid_too_long": "That's too long. Please keep the search under {max} characters.",
    "invalid_no_content": "I couldn't find any words to search for. Try a product name.",
    "not_allowed": "Sorry, this bot is private.",
    "rate_limited": "Too many requests. Please try again in {seconds} s.",
    "quota_blocked": "Your access to searches is currently disabled.",
    "session_expired": "These results have expired. Send the product name again.",
    "unexpected_error": "Something went wrong. Please try again.",
}

RU: dict[str, str] = {
    # --- onboarding ---
    "choose_language": "Choose your language / Выберите язык",
    "language_set": "Язык: русский.",
    "choose_city": "В каком городе искать?",
    "city_set": (
        "Город: <b>{city}</b>. Теперь отправьте название товара, например <b>iphone 13</b>."
    ),
    "need_city": "Сначала выберите город, затем отправьте запрос ещё раз.",
    "help": (
        "<b>Как это работает</b>\n"
        "Отправьте название товара (по-русски или по-английски), например "
        "<i>iphone 13 128gb</i> или <i>велосипед горный</i>. Я ищу на Bazaraki и в "
        "Telegram-группах и показываю цены, выгодные предложения и объявления.\n\n"
        "/city - сменить город\n/lang - сменить язык\n/help - эта справка"
    ),
    # --- cities ---
    "city.nicosia": "Никосия",
    "city.limassol": "Лимассол",
    "city.larnaca": "Ларнака",
    "city.paphos": "Пафос",
    "city.famagusta": "Фамагуста",
    "city.all": "Весь Кипр",
    "city.unknown": "город не указан",
    # --- search progress ---
    "searching": "🔎 Ищу <b>{query}</b>: {city}…",
    "progress_done": "✅ {source}: {count}",
    "progress_failed": "⚠️ {source}: недоступен",
    "progress_waiting": "⏳ {source}…",
    # --- results ---
    "header": "🔎 <b>{query}</b> · {city}",
    "found_per_source": "Найдено {total}: {parts}",
    "source_unavailable": "{source} ⚠️",
    "partial_note": "⚠️ Не удалось получить результаты: {sources}. Показаны неполные результаты.",
    "stats_title": "💶 <b>Цены (EUR)</b> — объявлений: {sample}",
    "stats_outliers": ", исключено выбросов: {removed}",
    "stats_line": "Средняя {average} · Медиана {median} · Мин {minimum} · Макс {maximum}",
    "stats_unreliable": "⚠️ Объявлений с ценой всего {count} — статистика ненадёжна.",
    "stats_none": "В этих объявлениях нет цен.",
    "stats_unpriced": "Объявления без цены ({count}) не учитываются.",
    "category_question": (
        "🗂 <b>Что вы ищете?</b>\n"
        "«{query}» подходит к разным видам объявлений. "
        "Выберите нужный, чтобы результаты были точнее.{where}"
    ),
    "category_where": "\nВ разделе: <b>{label}</b>",
    "category_option": "{label} ({count})",
    "btn_any_category": "🔎 Любая категория",
    "category_line": "🗂 Категория: {category}",
    "category_expired": "Этот вопрос устарел. Отправьте запрос ещё раз.",
    "unusual_hidden": "🚫 Скрыто объявлений с необычной ценой: {count} ({detail})",
    "unusual_low": "ниже {price}",
    "unusual_high": "выше {price}",
    "unusual_mixed": (
        "ℹ️ Цены здесь сильно различаются, поэтому статистика может быть нерепрезентативной. "
        "Уточните запрос."
    ),
    "unusual_shown": "⚠️ Объявления с необычной ценой помечены ⚠️ и не учитываются в статистике.",
    "filter_unusual": "Необычные цены: {value}",
    "unusual.hidden": "скрыты",
    "unusual.shown": "показаны",
    "summary_unusual": "необычные цены показаны",
    "deals_title": "🏷 <b>Выгодные предложения</b>",
    "deal_line": '{index}. <a href="{url}">{title}</a> — {price} (на {discount}% ниже медианы)',
    "page_title": "📄 <b>Объявления</b> — страница {page}/{pages}",
    "card_price_none": "цена не указана",
    "card_posted": "размещено {date}",
    "btn_prev": "◀ Назад",
    "btn_next": "Вперёд ▶",
    # --- filters ---
    "btn_filters": "⚙️ Фильтры",
    "btn_reset_filters": "✖ Сбросить фильтры",
    "btn_back": "◀ К результатам",
    "btn_cancel": "Отмена",
    "btn_min_price": "Мин. цена",
    "btn_max_price": "Макс. цена",
    "filters_title": "⚙️ <b>Фильтры</b>",
    "filter_price": "Цена: {value}",
    "filter_sort": "Сортировка: {value}",
    "filter_source": "Источник: {value}",
    "price_any": "любая",
    "price_range": "{low} – {high}",
    "price_from": "от {low}",
    "price_upto": "до {high}",
    "sort.newest": "Сначала новые",
    "sort.cheapest": "Сначала дешёвые",
    "sort.best_deal": "Выгодные",
    "source.all": "Все источники",
    "filters_matching": "Подходит объявлений: {shown} из {total}.",
    "filters_active": "🔧 <b>Фильтры:</b> {summary} — показано {shown} из {total}",
    "prompt_min_price": (
        "Отправьте <b>минимальную</b> цену в евро, например <i>150</i>. 0 — убрать ограничение."
    ),
    "prompt_max_price": (
        "Отправьте <b>максимальную</b> цену в евро, например <i>500</i>. 0 — убрать ограничение."
    ),
    "price_range_error": "Минимум не может быть больше максимума. Попробуйте другое число.",
    "no_match_filters": "Под ваши фильтры ничего не подходит (до фильтрации найдено: {total}).",
    "non_text": "Я понимаю только текст. Отправьте название товара для поиска.",
    "btn_page": "{page}/{pages}",
    # --- problems ---
    "no_results": (
        "По запросу <b>{query}</b> ничего не найдено ({city}).\n"
        "Попробуйте более общий запрос (меньше слов, без характеристик), другое написание "
        "или выберите <b>Весь Кипр</b> через /city."
    ),
    "all_failed": "Сейчас не удалось связаться ни с одним источником. Попробуйте через минуту.",
    "invalid_empty": "Отправьте название товара для поиска.",
    "invalid_too_long": "Слишком длинный запрос. Уложитесь в {max} символов.",
    "invalid_no_content": "Не нашёл слов для поиска. Попробуйте название товара.",
    "not_allowed": "Извините, этот бот приватный.",
    "rate_limited": "Слишком много запросов. Попробуйте через {seconds} с.",
    "quota_blocked": "Доступ к поиску сейчас отключён.",
    "session_expired": "Эти результаты устарели. Отправьте название товара ещё раз.",
    "unexpected_error": "Что-то пошло не так. Попробуйте ещё раз.",
}

CATALOGS: dict[str, dict[str, str]] = {"en": EN, "ru": RU}


class Texts:
    """Translator bound to one language. Missing keys fall back to English; a key missing from
    English is a bug and raises."""

    def __init__(self, language: str = DEFAULT_LANGUAGE) -> None:
        self.language = language if language in CATALOGS else DEFAULT_LANGUAGE
        self._catalog = CATALOGS[self.language]

    def __call__(self, key: str, **params: Any) -> str:
        template = self._catalog.get(key) or EN[key]
        return template.format(**params) if params else template

    def city(self, city_value: str) -> str:
        return self(f"city.{city_value}")
