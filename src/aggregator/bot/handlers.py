"""aiogram handlers. Thin by design: parse the update, call a service, render the answer."""

from __future__ import annotations

import structlog
from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from aggregator.bot import keyboards
from aggregator.bot.context import Services
from aggregator.bot.formatting import clamp_page, format_empty, format_results, page_count
from aggregator.bot.i18n import Texts
from aggregator.bot.progress import ProgressMessage
from aggregator.domain.cities import City
from aggregator.services.quota import check_quota
from aggregator.services.search_service import InvalidQueryError
from aggregator.services.sessions import SearchSession
from aggregator.services.users import SUPPORTED_LANGUAGES, UserProfile

log = structlog.get_logger()


# --- helpers --------------------------------------------------------------------------------


async def _user_for(message: Message | CallbackQuery, services: Services) -> UserProfile | None:
    tg_user = message.from_user
    if tg_user is None:
        return None
    return await services.users.ensure_user(tg_user.id, tg_user.language_code)


def render_session(
    t: Texts, services: Services, session: SearchSession
) -> tuple[str, InlineKeyboardMarkup | None]:
    """Text and keyboard for the session's current page."""
    view = services.search.view(session.outcome, session.filters)
    if not view.listings:
        return format_empty(t, session.outcome), None
    page = clamp_page(session.page, len(view.listings))
    text = format_results(t, session.outcome, view, page)
    return text, keyboards.pager_keyboard(t, page, page_count(len(view.listings)))


# --- onboarding / settings ------------------------------------------------------------------


async def cmd_start(message: Message, services: Services) -> None:
    if await _user_for(message, services) is None:
        return
    await message.answer(Texts()("choose_language"), reply_markup=keyboards.language_keyboard())


async def cmd_lang(message: Message, services: Services) -> None:
    if await _user_for(message, services) is None:
        return
    await message.answer(Texts()("choose_language"), reply_markup=keyboards.language_keyboard())


async def cmd_city(message: Message, services: Services) -> None:
    user = await _user_for(message, services)
    if user is None:
        return
    t = Texts(user.language)
    await message.answer(t("choose_city"), reply_markup=keyboards.city_keyboard(t))


async def cmd_help(message: Message, services: Services) -> None:
    user = await _user_for(message, services)
    if user is not None:
        await message.answer(Texts(user.language)("help"))


async def on_language(callback: CallbackQuery, services: Services) -> None:
    user = await _user_for(callback, services)
    code = (callback.data or "").removeprefix(keyboards.LANG_PREFIX)
    if user is None or code not in SUPPORTED_LANGUAGES or not isinstance(callback.message, Message):
        await callback.answer()
        return
    user = await services.users.set_language(user.telegram_id, code)
    t = Texts(user.language)
    if user.city is None:  # first run: continue straight to city selection
        await callback.message.edit_text(
            f"{t('language_set')}\n\n{t('choose_city')}", reply_markup=keyboards.city_keyboard(t)
        )
    else:
        await callback.message.edit_text(t("language_set"))
    await callback.answer()


async def on_city(callback: CallbackQuery, services: Services) -> None:
    user = await _user_for(callback, services)
    value = (callback.data or "").removeprefix(keyboards.CITY_PREFIX)
    try:
        city = City(value)
    except ValueError:
        await callback.answer()
        return
    if user is None or not isinstance(callback.message, Message):
        await callback.answer()
        return
    try:
        user = await services.users.set_city(user.telegram_id, city)
    except ValueError:  # not a selectable city (e.g. a forged callback)
        await callback.answer()
        return
    t = Texts(user.language)
    await callback.message.edit_text(t("city_set", city=t.city(city.value)))
    await callback.answer()


# --- search ---------------------------------------------------------------------------------


async def on_search(message: Message, services: Services) -> None:
    user = await _user_for(message, services)
    if user is None or message.text is None:
        return
    t = Texts(user.language)

    try:
        query = services.search.validate_query(message.text)
    except InvalidQueryError as exc:
        await message.answer(t(f"invalid_{exc.reason}", max=services.search.max_query_length))
        return
    if not check_quota(user).allowed:
        await message.answer(t("quota_blocked"))
        return
    if user.city is None:
        await message.answer(t("need_city"), reply_markup=keyboards.city_keyboard(t))
        return

    progress = ProgressMessage(message, t, query, user.city, services.source_names)
    await progress.start()
    try:
        outcome = await services.search.search(user, query, progress.on_status)
    except InvalidQueryError as exc:  # raced with a config change; same handling as above
        await progress.finish(t(f"invalid_{exc.reason}", max=services.search.max_query_length))
        return
    except Exception:
        log.exception("search.failed")
        await progress.finish(t("unexpected_error"))
        return

    session = SearchSession(outcome=outcome)
    await services.sessions.save(user.telegram_id, session)
    text, markup = render_session(t, services, session)
    await progress.finish(text, markup)


async def on_page(callback: CallbackQuery, services: Services) -> None:
    user = await _user_for(callback, services)
    if user is None or not isinstance(callback.message, Message):
        await callback.answer()
        return
    t = Texts(user.language)
    try:
        page = int((callback.data or "").removeprefix(keyboards.PAGE_PREFIX))
    except ValueError:
        await callback.answer()
        return

    session = await services.sessions.get(user.telegram_id)
    if session is None:
        await callback.answer(t("session_expired"), show_alert=True)
        return
    session.page = page
    text, markup = render_session(t, services, session)
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except TelegramAPIError:
        log.debug("page.edit_skipped", exc_info=True)  # e.g. same page tapped twice
    else:
        await services.sessions.save(user.telegram_id, session)
    await callback.answer()


async def on_noop(callback: CallbackQuery) -> None:
    await callback.answer()


def build_router() -> Router:
    """A fresh router per dispatcher (a router can only be attached to one)."""
    router = Router(name="main")
    router.message.register(cmd_start, CommandStart())
    router.message.register(cmd_lang, Command("lang"))
    router.message.register(cmd_city, Command("city"))
    router.message.register(cmd_help, Command("help"))
    router.callback_query.register(on_language, F.data.startswith(keyboards.LANG_PREFIX))
    router.callback_query.register(on_city, F.data.startswith(keyboards.CITY_PREFIX))
    router.message.register(on_search, F.text & ~F.text.startswith("/"))
    router.callback_query.register(on_page, F.data.startswith(keyboards.PAGE_PREFIX))
    router.callback_query.register(on_noop, F.data == keyboards.NOOP)
    return router
