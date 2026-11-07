"""aiogram handlers. Thin by design: parse the update, call a service, render the answer."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import structlog
from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from aggregator.bot import keyboards
from aggregator.bot.context import Services
from aggregator.bot.formatting import (
    clamp_page,
    format_category_question,
    format_empty,
    format_filters_menu,
    format_no_match,
    format_results,
    page_count,
)
from aggregator.bot.i18n import Texts
from aggregator.bot.progress import ProgressMessage
from aggregator.domain.cities import City
from aggregator.domain.models import ExpandedQuery, Filters
from aggregator.search.category_choice import Ask, Decision, Resolved
from aggregator.services.filters import (
    FilterError,
    parse_price_input,
    set_price_bound,
    set_sort,
    set_source,
    toggle_unusual_prices,
)
from aggregator.services.pending import PendingSearch
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


Screen = tuple[str, InlineKeyboardMarkup | None]


def render_results(t: Texts, services: Services, session: SearchSession) -> Screen:
    """Text and keyboard for the current page, with the session's filters applied."""
    filters = session.filters
    if not session.outcome.listings:
        return format_empty(t, session.outcome), None
    view = services.search.view(session.outcome, filters)
    if not view.listings:  # filters exclude everything: keep Filters/Reset reachable
        keyboard = keyboards.results_keyboard(t, 0, 1, filters_active=True)
        return format_no_match(t, session.outcome, filters), keyboard
    page = clamp_page(session.page, len(view.listings))
    text = format_results(
        t, session.outcome, view, page, filters, show_deals=services.show_best_deals
    )
    keyboard = keyboards.results_keyboard(
        t, page, page_count(len(view.listings)), filters_active=not filters.is_default
    )
    return text, keyboard


def render_filters_menu(t: Texts, services: Services, session: SearchSession) -> Screen:
    view = services.search.view(session.outcome, session.filters)
    text = format_filters_menu(t, session.outcome, view, session.filters)
    return text, keyboards.filters_keyboard(t, session.filters, services.source_names)


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

    await services.pending.clear(user.telegram_id)  # a new search replaces an unanswered question
    progress = ProgressMessage(message, t, query, user.city, services.source_names)
    await progress.start()

    # First look at which categories the results fall in: that may need a question to the user.
    plan = None
    try:
        plan = await services.search.plan_category(user, query)
    except InvalidQueryError as exc:  # raced with a config change; same handling as above
        await progress.finish(t(f"invalid_{exc.reason}", max=services.search.max_query_length))
        return
    except Exception:  # never let the category step block a search
        log.exception("search.plan_failed")

    if plan is not None and isinstance(plan.decision, Ask):
        pending = PendingSearch(
            text=query,
            query=plan.query,
            counts=dict(plan.counts),
            intent=plan.intent,
            prefix=plan.decision.prefix,
            options=[o.path for o in plan.decision.options],
        )
        await services.pending.save(user.telegram_id, pending)
        await progress.finish(
            format_category_question(t, query, plan.decision.prefix),
            keyboards.category_keyboard(t, plan.decision.options, plan.decision.prefix),
        )
        return

    category = (
        plan.decision.path if plan is not None and isinstance(plan.decision, Resolved) else None
    )
    await _search_and_show(
        progress, user, services, t, query, category, plan.query if plan is not None else None
    )


async def _search_and_show(
    progress: ProgressMessage,
    user: UserProfile,
    services: Services,
    t: Texts,
    text: str,
    category: str | None,
    expanded: ExpandedQuery | None,
) -> None:
    """Run the search (optionally inside a category) and replace the progress message with it."""
    try:
        outcome = await services.search.search(
            user, text, progress.on_status, category=category, query=expanded
        )
    except InvalidQueryError as exc:
        await progress.finish(t(f"invalid_{exc.reason}", max=services.search.max_query_length))
        return
    except Exception:
        log.exception("search.failed")
        await progress.finish(t("unexpected_error"))
        return

    session = SearchSession(outcome=outcome)
    await services.sessions.save(user.telegram_id, session)
    text_out, markup = render_results(t, services, session)
    await progress.finish(text_out, markup)


async def on_category(callback: CallbackQuery, services: Services) -> None:
    """The user answered a category question (`c:<option index>` or `c:any`)."""
    user = await _user_for(callback, services)
    if user is None or not isinstance(callback.message, Message):
        await callback.answer()
        return
    t = Texts(user.language)
    pending = await services.pending.get(user.telegram_id)
    if pending is None:
        await callback.answer(t("category_expired"), show_alert=True)
        return

    raw = (callback.data or "").removeprefix(keyboards.CATEGORY_PREFIX)
    decision: Decision
    if raw == keyboards.ANY_CATEGORY:
        decision = Resolved(None)
    else:
        try:
            chosen = pending.options[int(raw)]
        except (ValueError, IndexError):  # forged or stale callback data
            await callback.answer()
            return
        decision = services.search.next_category_step(pending.counts, chosen, pending.intent)
    await callback.answer()

    if isinstance(decision, Ask):  # the next level of the tree needs a question as well
        pending.prefix = decision.prefix
        pending.options = [o.path for o in decision.options]
        await services.pending.save(user.telegram_id, pending)
        try:
            await callback.message.edit_text(
                format_category_question(t, pending.text, decision.prefix),
                reply_markup=keyboards.category_keyboard(t, decision.options, decision.prefix),
            )
        except TelegramAPIError:
            log.debug("category.edit_skipped", exc_info=True)
        return

    await services.pending.clear(user.telegram_id)
    progress = ProgressMessage(
        callback.message,
        t,
        pending.text,
        user.city or City.ALL_CYPRUS,
        services.source_names,
        existing=callback.message,
    )
    await progress.start()
    await _search_and_show(progress, user, services, t, pending.text, decision.path, pending.query)


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
    text, markup = render_results(t, services, session)
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except TelegramAPIError:
        log.debug("page.edit_skipped", exc_info=True)  # e.g. same page tapped twice
    else:
        await services.sessions.save(user.telegram_id, session)
    await callback.answer()


# --- filters --------------------------------------------------------------------------------


def _apply_filter_action(
    action: str, t: Texts, services: Services, session: SearchSession
) -> Screen:
    """Mutates `session` for one `f:<action>` tap and returns the screen to show."""
    session.pending_price = None
    if action == "back":
        return render_results(t, services, session)
    if action == "reset":
        session.filters, session.page = Filters(), 0
        return render_results(t, services, session)
    if action == "reset:menu":
        session.filters, session.page = Filters(), 0
    elif action.startswith("sort:"):
        session.filters = set_sort(session.filters, action.removeprefix("sort:"))
        session.page = 0
    elif action == "odd":
        session.filters = toggle_unusual_prices(session.filters)
        session.page = 0
    elif action.startswith("src:"):
        chosen = action.removeprefix("src:")
        source = None if chosen == keyboards.ALL_SOURCES else chosen
        session.filters = set_source(session.filters, source, services.source_names)
        session.page = 0
    elif action in ("price:min", "price:max"):
        if action.endswith("min"):
            session.pending_price = "min"
            return t("prompt_min_price"), keyboards.price_prompt_keyboard(t)
        session.pending_price = "max"
        return t("prompt_max_price"), keyboards.price_prompt_keyboard(t)
    elif action != "menu":
        raise FilterError("unknown_action")
    return render_filters_menu(t, services, session)


async def on_filter(callback: CallbackQuery, services: Services) -> None:
    user = await _user_for(callback, services)
    if user is None or not isinstance(callback.message, Message):
        await callback.answer()
        return
    t = Texts(user.language)
    session = await services.sessions.get(user.telegram_id)
    if session is None:
        await callback.answer(t("session_expired"), show_alert=True)
        return
    action = (callback.data or "").removeprefix(keyboards.FILTER_PREFIX)
    try:
        text, markup = _apply_filter_action(action, t, services, session)
    except FilterError:  # forged or stale callback data
        await callback.answer()
        return
    session.anchor_message_id = callback.message.message_id
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except TelegramAPIError:
        log.debug("filter.edit_skipped", exc_info=True)  # e.g. the same option tapped twice
    await services.sessions.save(user.telegram_id, session)
    await callback.answer()


async def awaiting_price(message: Message, services: Services) -> bool | dict[str, Any]:
    """Filter: the user was asked for a min/max price and this message is a bare number.
    Anything else (e.g. a new product name) falls through to a normal search."""
    if message.from_user is None or not message.text:
        return False
    session = await services.sessions.get(message.from_user.id)
    if session is None or session.pending_price is None:
        return False
    price = parse_price_input(message.text)
    if price is None:
        return False
    return {"session": session, "price": price}


async def on_price_input(
    message: Message, services: Services, session: SearchSession, price: Decimal
) -> None:
    user = await _user_for(message, services)
    field = session.pending_price
    if user is None or field is None:
        return
    t = Texts(user.language)
    try:
        session.filters = set_price_bound(session.filters, field, price)
    except FilterError:
        await message.answer(t("price_range_error"))  # still waiting for a valid number
        return
    session.pending_price, session.page = None, 0
    text, markup = render_filters_menu(t, services, session)
    await services.sessions.save(user.telegram_id, session)

    if session.anchor_message_id is not None and message.bot is not None:
        try:
            await message.bot.edit_message_text(
                text,
                chat_id=message.chat.id,
                message_id=session.anchor_message_id,
                reply_markup=markup,
            )
        except TelegramAPIError:
            log.debug("price.anchor_edit_failed", exc_info=True)
        else:
            return
    await message.answer(text, reply_markup=markup)


async def on_non_text(message: Message, services: Services) -> None:
    user = await _user_for(message, services)
    if user is not None:
        await message.answer(Texts(user.language)("non_text"))


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
    router.message.register(
        on_price_input, awaiting_price
    )  # before on_search: it may claim a number
    router.message.register(on_search, F.text & ~F.text.startswith("/"))
    router.message.register(on_non_text, F.chat.type == "private", ~F.text)
    router.callback_query.register(on_category, F.data.startswith(keyboards.CATEGORY_PREFIX))
    router.callback_query.register(on_page, F.data.startswith(keyboards.PAGE_PREFIX))
    router.callback_query.register(on_filter, F.data.startswith(keyboards.FILTER_PREFIX))
    router.callback_query.register(on_noop, F.data == keyboards.NOOP)
    return router
