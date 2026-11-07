"""Spam in the Telegram groups: what is recognised, and (just as important) what is left alone."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from aggregator.sources.telegram.indexer import Indexer
from aggregator.sources.telegram.ingest import IngestAction, ingest_message
from aggregator.sources.telegram.parser import parse_message
from aggregator.sources.telegram.spam import spam_reason

# --- real spam, copied from the stored messages --------------------------------------------

SPAM = [
    # Chinese "earn money" posts
    (
        "cjk",
        "招大量地推人员\n拍私家车100元一单 拍商铺资料100元一单 拍商家收款码80元一单 做单群: @SSSCCCNNN168",
    ),
    ("cjk", "代刷项目日入过万"),
    # Recruitment bots that dodge filters with look-alike letters
    (
        "lookalike_letters",
        "ИЩY Lюдей в koманду на\nObучение. ✅Опыt не требуется ✅БЕСПЛАТHOE OБУЧЕНИЕ "
        "Зарабоtok 150-200💵 в неделю. ✅Все что нужно - телефон и желание pаботать, "
        "всему научy ➡Связь: @Manches1eR1",
    ),
    # Posts with no text at all: a link, or a row of emoji digits
    ("no_text", "https://t.me/m/FVlXS0AJM2Rk"),
    ("no_text", "1⃣0⃣0⃣0⃣0⃣\n🔠🔠 2️⃣0️⃣0️⃣0️⃣0️⃣ 🔠🔠🔠 https://t.me/m/i2LCQG10ZTAx"),
    ("no_text", "€25"),
    # Job offers
    (
        "job_offer",
        "Есть свободные? Предлагаем работу с ежедневной оплатой!\n"
        "Доход от 2000 грн в день. Деньги выплачиваются сразу после выполнения работы. "
        "Заинтересовало — обращайтесь! TG: @ZXZX_0101",
    ),
    (
        "lookalike_letters",  # the Latin "i" inside Ukrainian words is the giveaway
        "Термiново потрiбнi хлопцi та дiвчата, для нескладної роботи у вільний час. "
        "Зайнятість 2 - 3 години в день\nОплата висока відразу на руки! "
        "Якщо зацікавлені, пишіть на наш TG:@tviy_vubirr",
    ),
    (
        "job_offer",
        "Потрібні підсобні робітники\n📍 Робота на об'єкті 💰 Оплата від 4000 грн — щодня, "
        "в кінці зміни Кому підійде: ▫️Вік 16–45 років ▫️Готовність до фізичної роботи",
    ),
    (
        "job_offer",
        "Мяу мяу шоп\nот 150$ за смену первая выручка уже сегондя ничё сложного пиши @StoryTe2",
    ),
    (
        "job_offer",
        "Предлагаю: Простая работа\nСвободный график — заходи по пути домой Без офиса — гуляй "
        "по городу и зарабатывай Оплата сразу после завершения работы @ZXZX_0101",
    ),
    (
        "job_offer",
        "Привет, открыли, набор на вакансию водителя, рейсы от 500 до 1000 км, "
        "оплата за рейс от 40 тысяч",
    ),
]


@pytest.mark.parametrize(("reason", "text"), SPAM)
def test_real_spam_is_recognised(reason: str, text: str) -> None:
    assert spam_reason(text) == reason


# --- real listings must never be touched ---------------------------------------------------

LEGIT = [
    "Продаю iPhone 13 в светлом цвете (Starlight)\nСостояние: Отличное. Работа устройств: все функции. 270€",
    "Холодильник работает отлично, оплата наличными, забрать в день покупки. Писать @seller_name",
    "Продам робот-пылесос Xiaomi — €50\nПылесос работает. Есть неисправность моющего блока.",
    "Аренда авто от 30€ в день. Пишите @rentcy_cars",  # a rental service, not a job
    "Сдаётся 2-спальная квартира, Лимассол, Гермасойя. Оплата помесячно, залог 1 месяц. "
    "Пишите @agent_limassol",
    "Toyota Vitz 1.3 Automatic CVT, 2007\nАвтомат CVT, не робот! Отличное состояние.",
    "iPhone 13 Про Макс 256gb, 450€",  # Latin and Cyrillic words next to each other
    "Xiaomi 小米 Redmi Note 11, 120€ Лимассол",  # two Chinese characters in a brand name
    "Продам коляску, стан відмінний, 100 євро, Лімасол",  # Ukrainian, a normal sale
    "Beautiful sofa, 80€, pickup Paphos",
    "Велосипед Trek FX 2\nЦена 250€, Лимассол",
    "3 bedroom apartment to rent in Limassol, 1500 euro per month, call +357 99 123456",
    "Нужен репетитор? Занятия по математике, 20€ в час. Пишите @tutor_cy",
]


@pytest.mark.parametrize("text", LEGIT)
def test_real_listings_are_left_alone(text: str) -> None:
    assert spam_reason(text) is None


def test_empty_text_is_not_spam_but_empty() -> None:
    assert spam_reason(None) is None
    assert spam_reason("   ") is None


# --- how it is used -------------------------------------------------------------------------


class FakeRepo:
    def __init__(self) -> None:
        self.upserts: list[Any] = []
        self.deleted: list[list[str]] = []

    async def upsert(self, listing: Any, *, is_active: bool = True, raw: Any = None) -> None:
        self.upserts.append(listing)

    async def mark_deleted(self, source: str, external_ids: list[str]) -> int:
        self.deleted.append(list(external_ids))
        return len(external_ids)


POSTED = datetime(2026, 11, 1, tzinfo=UTC)


async def ingest(repo: FakeRepo, text: str, **kwargs: Any) -> IngestAction:
    return await ingest_message(
        repo,
        chat_id=1,
        message_id=2,
        username="g",
        text=text,
        posted_at=POSTED,
        **kwargs,
    )


async def test_spam_is_not_stored() -> None:
    repo = FakeRepo()
    action = await ingest(repo, SPAM[0][1])
    assert action is IngestAction.SKIPPED_SPAM
    assert repo.upserts == []


async def test_a_post_edited_into_spam_is_hidden_on_live_events_only() -> None:
    live, backfill = FakeRepo(), FakeRepo()
    await ingest(live, SPAM[0][1], deactivate_existing=True)
    await ingest(backfill, SPAM[0][1], deactivate_existing=False)
    assert live.deleted == [["1:2"]]
    assert backfill.deleted == []


async def test_a_real_listing_is_still_stored() -> None:
    repo = FakeRepo()
    assert await ingest(repo, "Велосипед Trek FX 2\nЦена 250€, Лимассол") is IngestAction.STORED


def test_the_parser_reports_the_reason() -> None:
    assert parse_message(SPAM[0][1]).spam == "cjk"
    assert parse_message("Велосипед Trek FX 2\nЦена 250€").spam is None


class FakePurgeRepo:
    def __init__(self, rows: list[tuple[str, str | None]]) -> None:
        self.rows = rows

    async def deactivate_where(self, source: str, is_unwanted: Any) -> int:
        return sum(1 for title, description in self.rows if is_unwanted(title, description))


async def test_the_indexer_purge_applies_the_same_rules_to_stored_rows() -> None:
    rows = [
        ("招大量地推人员", "拍私家车100元一单 做单群"),  # spam
        ("Велосипед Trek FX 2", "Цена 250€, Лимассол"),  # fine
        ("https://t.me/m/FVlXS0AJM2Rk", None),  # spam: only a link
    ]
    indexer = Indexer(
        client=None,  # type: ignore[arg-type]
        repository=FakePurgeRepo(rows),  # type: ignore[arg-type]
        backfill_days=30,
        max_age_days=30,
    )
    assert await indexer.purge_spam() == 2
