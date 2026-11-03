"""Bot transport: long polling now; the webhook switch is isolated here so handlers never change."""

from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from aggregator.bot import handlers
from aggregator.bot.context import Services
from aggregator.bot.middlewares import AccessMiddleware, RateLimitMiddleware
from aggregator.config import Settings
from aggregator.services.ratelimit import SlidingWindowRateLimiter

_COMMANDS = {
    "en": [
        BotCommand(command="start", description="Start"),
        BotCommand(command="city", description="Change city"),
        BotCommand(command="lang", description="Change language"),
        BotCommand(command="help", description="Help"),
    ],
    "ru": [
        BotCommand(command="start", description="Начать"),
        BotCommand(command="city", description="Сменить город"),
        BotCommand(command="lang", description="Сменить язык"),
        BotCommand(command="help", description="Справка"),
    ],
}


def create_bot(token: str, session: BaseSession | None = None) -> Bot:
    return Bot(
        token=token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )


def build_dispatcher(services: Services, settings: Settings) -> Dispatcher:
    dispatcher = Dispatcher(services=services)
    access = AccessMiddleware(settings.allowed_user_ids)
    dispatcher.message.outer_middleware(access)
    dispatcher.callback_query.outer_middleware(access)
    if settings.rate_limit_enabled:
        limiter = SlidingWindowRateLimiter(
            settings.rate_limit_requests, settings.rate_limit_window_seconds
        )
        dispatcher.message.outer_middleware(RateLimitMiddleware(limiter))
    dispatcher.include_router(handlers.build_router())
    return dispatcher


async def set_commands(bot: Bot) -> None:
    await bot.set_my_commands(_COMMANDS["en"])
    await bot.set_my_commands(_COMMANDS["ru"], language_code="ru")


async def run_polling(bot: Bot, dispatcher: Dispatcher) -> None:
    await bot.delete_webhook(drop_pending_updates=False)
    await set_commands(bot)
    await dispatcher.start_polling(bot)


async def run_webhook(bot: Bot, dispatcher: Dispatcher, settings: Settings) -> None:
    """Reserved for a public deployment (`BOT_MODE=webhook`): mount aiogram's
    `SimpleRequestHandler` on an aiohttp app, call `bot.set_webhook(...)`, and reuse the same
    dispatcher. Nothing outside this module needs to change."""
    raise NotImplementedError("webhook mode is not implemented yet; use BOT_MODE=polling")
