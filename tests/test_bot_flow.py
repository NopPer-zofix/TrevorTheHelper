"""End-to-end bot flow through the real dispatcher, middlewares and handlers.

The only fake is the Telegram transport (`RecordingSession`) and the listing sources."""

from __future__ import annotations

import re
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage, TelegramMethod
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from aggregator.bot import handlers
from aggregator.bot.context import Services
from aggregator.bot.runner import build_dispatcher, create_bot
from aggregator.cache import InMemoryTTLCache
from aggregator.config import Settings
from aggregator.domain.cities import City
from aggregator.query import QueryExpander
from aggregator.search.orchestrator import SearchOrchestrator
from aggregator.services.pending import PendingSearch, PendingStore
from aggregator.services.search_service import SearchService
from aggregator.services.sessions import SearchSession, SessionStore
from aggregator.services.users import InMemoryUserStore, UserService
from aggregator.sources.base import CategoryExplorer, SourceError
from factories import make_listing
from test_orchestrator import FakeSource

USER_ID = 42
CHAT_ID = 42


class RecordingSession(BaseSession):
    """Records every Bot API call and answers with a plausible result."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod[Any]] = []
        self._next_id = 1000

    async def close(self) -> None:
        return None

    async def stream_content(self, *args: Any, **kwargs: Any) -> AsyncGenerator[bytes, None]:
        yield b""

    async def make_request(self, bot: Bot, method: TelegramMethod[Any], timeout: Any = None) -> Any:  # noqa: ASYNC109
        self.calls.append(method)
        if isinstance(method, SendMessage | EditMessageText):
            self._next_id += 1
            chat_id = method.chat_id if isinstance(method.chat_id, int) else CHAT_ID
            message = Message(
                message_id=getattr(method, "message_id", None) or self._next_id,
                date=datetime.now(UTC),
                chat=Chat(id=chat_id, type="private"),
                text=method.text,
            )
            return message.as_(bot)
        return True

    # --- helpers for assertions ---
    def of(self, kind: type[TelegramMethod[Any]]) -> list[Any]:
        return [c for c in self.calls if isinstance(c, kind)]

    @property
    def last_text(self) -> str:
        texts = [c.text for c in self.calls if isinstance(c, SendMessage | EditMessageText)]
        return texts[-1]

    def buttons(self, call: Any) -> list[str]:
        markup = call.reply_markup
        return [b.callback_data for row in markup.inline_keyboard for b in row] if markup else []


class Harness:
    def __init__(self, sources: list[Any], settings: Settings) -> None:
        self.session = RecordingSession()
        self.bot = create_bot("123456:TEST-TOKEN", self.session)
        self.users = UserService(InMemoryUserStore())
        self.sessions = SessionStore(InMemoryTTLCache[SearchSession](), 3600)
        self.pending = PendingStore(InMemoryTTLCache[PendingSearch](), 900)
        self.services = Services(
            users=self.users,
            search=SearchService(
                QueryExpander(llm=None),
                SearchOrchestrator(sources, source_timeout_seconds=1),
                explorers=[s for s in sources if isinstance(s, CategoryExplorer)],
            ),
            sessions=self.sessions,
            pending=self.pending,
            source_names=[s.name for s in sources],
        )
        self.dp: Dispatcher = build_dispatcher(self.services, settings)
        self._update_id = 0
        self.last_host_id = 0  # id of the message the last tapped button was attached to

    def _user(self, user_id: int = USER_ID, lang: str = "en") -> User:
        return User(id=user_id, is_bot=False, first_name="T", language_code=lang)

    async def say(self, text: str, user_id: int = USER_ID, lang: str = "en") -> None:
        self._update_id += 1
        message = Message(
            message_id=self._update_id,
            date=datetime.now(UTC),
            chat=Chat(id=user_id, type="private"),
            from_user=self._user(user_id, lang),
            text=text,
        )
        await self.dp.feed_update(self.bot, Update(update_id=self._update_id, message=message))

    async def send_without_text(self, user_id: int = USER_ID) -> None:
        """A message with no text at all (photo, sticker, voice...)."""
        self._update_id += 1
        message = Message(
            message_id=self._update_id,
            date=datetime.now(UTC),
            chat=Chat(id=user_id, type="private"),
            from_user=self._user(user_id),
        )
        await self.dp.feed_update(self.bot, Update(update_id=self._update_id, message=message))

    async def tap(self, data: str, user_id: int = USER_ID, lang: str = "en") -> None:
        self._update_id += 1
        host = Message(
            message_id=500 + self._update_id,
            date=datetime.now(UTC),
            chat=Chat(id=user_id, type="private"),
            text="previous bot message",
        )
        self.last_host_id = host.message_id
        callback = CallbackQuery(
            id=str(self._update_id),
            from_user=self._user(user_id, lang),
            chat_instance="x",
            data=data,
            message=host,
        )
        await self.dp.feed_update(
            self.bot, Update(update_id=self._update_id, callback_query=callback)
        )


def sources_with_listings(count: int = 7) -> list[Any]:
    bazaraki = [
        make_listing(
            f"iPhone 13 128GB #{i}", price=400 + i * 10, source="bazaraki", external_id=f"b{i}"
        )
        for i in range(count)
    ]
    telegram = [
        make_listing("Айфон 13", price=380, source="telegram", external_id="t1", days_old=2),
        make_listing("Чехол для iPhone 13", price=10, source="telegram", external_id="t2"),
    ]
    return [FakeSource("bazaraki", bazaraki), FakeSource("telegram", telegram)]


def settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


@pytest.fixture
def harness() -> Harness:
    return Harness(sources_with_listings(), settings())


async def onboard(h: Harness, city: str = "limassol") -> None:
    await h.say("/start")
    await h.tap("lang:en")
    await h.tap(f"city:{city}")


# --- onboarding ---------------------------------------------------------------------------


async def test_start_offers_language_then_city_then_confirms(harness: Harness) -> None:
    await harness.say("/start")
    start = harness.session.of(SendMessage)[-1]
    assert harness.session.buttons(start) == ["lang:en", "lang:ru"]

    await harness.tap("lang:ru")
    edit = harness.session.of(EditMessageText)[-1]
    assert "русский" in edit.text
    assert "city:limassol" in harness.session.buttons(edit)
    assert "city:all" in harness.session.buttons(edit)

    await harness.tap("city:limassol")
    assert "Лимассол" in harness.session.last_text
    user = await harness.users.ensure_user(USER_ID)
    assert (user.language, user.city) == ("ru", City.LIMASSOL)


async def test_forged_city_callbacks_are_ignored(harness: Harness) -> None:
    await harness.say("/start")
    await harness.tap("city:atlantis")
    await harness.tap("city:unknown")  # exists as an enum value but is not selectable
    assert (await harness.users.ensure_user(USER_ID)).city is None


async def test_searching_before_choosing_a_city_asks_for_one(harness: Harness) -> None:
    await harness.say("iphone 13")
    reply = harness.session.of(SendMessage)[-1]
    assert "choose a city" in reply.text.lower()
    assert "city:limassol" in harness.session.buttons(reply)


# --- the main flow ------------------------------------------------------------------------


async def test_search_edits_one_message_and_shows_stats_deals_and_cards(
    harness: Harness,
) -> None:
    await onboard(harness)
    sent_before = len(harness.session.of(SendMessage))

    await harness.say("iphone 13")

    # exactly ONE new message (the progress message), later edited into the result
    assert len(harness.session.of(SendMessage)) == sent_before + 1
    progress = harness.session.of(SendMessage)[-1]
    assert "Searching" in progress.text

    final = harness.session.of(EditMessageText)[-1]
    text = final.text
    assert "iphone 13" in text and "Limassol" in text
    assert "Bazaraki 7" in text and "Telegram 1" in text  # accessory filtered out
    assert "Average" in text and "Median" in text and "Min" in text and "Max" in text
    assert "Listings" in text and "1/2" in text  # 8 listings -> 2 pages of 5
    assert "Чехол" not in text
    assert harness.session.buttons(final) == ["noop", "pg:1", "f:menu"]
    assert re.search(r'<a href="https://example\.test/[^"]+">', text)
    assert len(text) <= 4096


async def test_handlers_pass_the_best_deals_flag_to_the_message(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The handler must forward `services.show_best_deals` (unit tests cover the formatting)."""
    seen: list[bool] = []
    real = handlers.format_results

    def spy(*args: Any, **kwargs: Any) -> str:
        seen.append(kwargs["show_deals"])
        return real(*args, **kwargs)

    monkeypatch.setattr(handlers, "format_results", spy)
    await onboard(harness)
    harness.services.show_best_deals = False
    await harness.say("iphone 13")
    harness.services.show_best_deals = True
    await harness.tap("pg:1")
    assert seen == [False, True]


async def test_progress_message_is_updated_as_sources_respond(harness: Harness) -> None:
    await onboard(harness)
    await harness.say("iphone 13")
    edits = [c.text for c in harness.session.of(EditMessageText)]
    assert any(("Bazaraki: 7" in e and "Telegram…" in e) or "Telegram: 1" in e for e in edits)


async def test_pagination_prev_next_and_expired_sessions(harness: Harness) -> None:
    await onboard(harness)
    await harness.say("iphone 13")

    await harness.tap("pg:1")
    page2 = harness.session.of(EditMessageText)[-1]
    assert "page 2/2" in page2.text
    assert harness.session.buttons(page2) == ["pg:0", "noop", "f:menu"]

    await harness.tap("pg:99")  # out of range is clamped, never crashes
    assert "page 2/2" in harness.session.of(EditMessageText)[-1].text

    await harness.sessions._cache.delete(f"search-session:{USER_ID}")
    await harness.tap("pg:0")
    alert = harness.session.of(AnswerCallbackQuery)[-1]
    assert alert.show_alert and "expired" in (alert.text or "")


async def test_russian_interface_and_russian_query() -> None:
    sources = [
        FakeSource(
            "bazaraki",
            [
                make_listing(f"Горный велосипед {i}", price=100 + i, external_id=str(i))
                for i in range(3)
            ],
        )
    ]
    h = Harness(sources, settings())
    await h.say("/start", lang="ru")
    await h.tap("lang:ru", lang="ru")
    await h.tap("city:all", lang="ru")
    await h.say("велосипед горный", lang="ru")

    text = h.session.of(EditMessageText)[-1].text
    assert "Весь Кипр" in text and "Цены" in text and "Найдено 3" in text
    assert "Average" not in text


async def test_unknown_city_listings_are_labelled_in_all_cyprus() -> None:
    sources = [
        FakeSource("telegram", [make_listing("iPhone 13", city=City.UNKNOWN, external_id="u")])
    ]
    h = Harness(sources, settings())
    await onboard(h, city="all")
    await h.say("iphone 13")
    assert "city not specified" in h.session.of(EditMessageText)[-1].text


# --- degradation and edge cases -----------------------------------------------------------


async def test_a_failing_source_gives_partial_results_and_a_note() -> None:
    sources = sources_with_listings()
    sources[1] = FakeSource("telegram", SourceError("index down"))
    h = Harness(sources, settings())
    await onboard(h)
    await h.say("iphone 13")

    text = h.session.of(EditMessageText)[-1].text
    assert "Bazaraki 7" in text
    assert "Telegram ⚠️" in text
    assert "Couldn't get results from Telegram" in text


async def test_all_sources_failing_and_empty_results_have_friendly_messages() -> None:
    h = Harness([FakeSource("bazaraki", SourceError("blocked"))], settings())
    await onboard(h)
    await h.say("iphone 13")
    assert "couldn't reach any source" in h.session.of(EditMessageText)[-1].text.lower()

    h2 = Harness([FakeSource("bazaraki", [])], settings())
    await onboard(h2)
    await h2.say("flux capacitor")
    text = h2.session.of(EditMessageText)[-1].text
    assert "Nothing found" in text and "broader" in text


@pytest.mark.parametrize(
    ("text", "expected"),
    [("   ", "product name"), ("🙂🙂🙂", "words to search"), ("x" * 101, "too long")],
)
async def test_invalid_input_is_rejected_without_searching(
    harness: Harness, text: str, expected: str
) -> None:
    await onboard(harness)
    searches_before = len(harness.services.search._orchestrator._sources[0].calls)  # type: ignore[attr-defined]
    await harness.say(text)
    assert expected in harness.session.of(SendMessage)[-1].text
    assert len(harness.services.search._orchestrator._sources[0].calls) == searches_before  # type: ignore[attr-defined]


async def test_html_in_listing_titles_is_escaped() -> None:
    nasty = make_listing("iPhone 13 <script>&", external_id="x")
    h = Harness([FakeSource("bazaraki", [nasty])], settings())
    await onboard(h)
    await h.say("iphone 13")
    text = h.session.of(EditMessageText)[-1].text
    assert "<script>" not in text
    assert "&lt;script&gt;&amp;" in text


async def test_html_in_the_users_query_is_escaped() -> None:
    h = Harness([FakeSource("bazaraki", [])], settings())
    await onboard(h)
    await h.say("iphone <i>13</i>")
    text = h.session.of(EditMessageText)[-1].text
    assert "&lt;i&gt;13&lt;/i&gt;" in text
    assert "<i>13</i>" not in text


async def test_commands_city_lang_help(harness: Harness) -> None:
    await onboard(harness)
    await harness.say("/city")
    assert "city:paphos" in harness.session.buttons(harness.session.of(SendMessage)[-1])
    await harness.say("/lang")
    assert "lang:ru" in harness.session.buttons(harness.session.of(SendMessage)[-1])
    await harness.say("/help")
    assert "How it works" in harness.session.last_text


# --- scalability hooks --------------------------------------------------------------------


async def test_private_mode_refuses_strangers_politely_and_serves_the_owner() -> None:
    h = Harness(sources_with_listings(), settings(allowed_user_ids=[USER_ID]))
    await h.say("/start", user_id=999)
    assert "private" in h.session.last_text
    await h.tap("city:limassol", user_id=999)
    assert h.session.of(AnswerCallbackQuery)[-1].show_alert

    await h.say("/start")  # the owner
    assert "language" in h.session.last_text.lower()


async def test_rate_limit_blocks_the_burst_but_not_other_users() -> None:
    h = Harness(
        sources_with_listings(),
        settings(rate_limit_enabled=True, rate_limit_requests=2, rate_limit_window_seconds=60),
    )
    await h.say("/help")
    await h.say("/help")
    n = len(h.session.of(SendMessage))
    await h.say("/help")
    assert "Too many requests" in h.session.last_text
    assert len(h.session.of(SendMessage)) == n + 1

    await h.say("/help", user_id=7)  # another user is unaffected
    assert "How it works" in h.session.last_text


async def test_blocked_users_cannot_search() -> None:
    h = Harness(sources_with_listings(), settings())
    await onboard(h)
    store = h.users._store  # type: ignore[attr-defined]
    store._users[USER_ID] = store._users[USER_ID].model_copy(update={"is_allowed": False})
    await h.say("iphone 13")
    assert "disabled" in h.session.of(SendMessage)[-1].text
