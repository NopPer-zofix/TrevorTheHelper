"""The Filters flow (min/max price, sort, source, reset) through the real dispatcher."""

from __future__ import annotations

import re

import pytest
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage

from test_bot_flow import (
    USER_ID,
    Harness,
    onboard,
    settings,
    sources_with_listings,
)


@pytest.fixture
def harness() -> Harness:
    return Harness(sources_with_listings(), settings())


def cards(text: str) -> list[str]:
    """Titles of the listing cards in a results message, in order."""
    return re.findall(r'^\d+\. <a href="[^"]+">([^<]+)</a>', text, flags=re.MULTILINE)


async def searched(h: Harness, query: str = "iphone 13") -> None:
    await onboard(h)
    await h.say(query)


async def test_filters_button_opens_the_menu_and_back_returns_to_results(
    harness: Harness,
) -> None:
    await searched(harness)
    await harness.tap("f:menu")
    menu = harness.session.of(EditMessageText)[-1]
    assert "Filters" in menu.text and "8 of 8 listings match" in menu.text
    data = set(harness.session.buttons(menu))
    assert {"f:sort:newest", "f:sort:cheapest", "f:sort:best_deal"} <= data
    assert {"f:src:all", "f:src:bazaraki", "f:src:telegram"} <= data
    assert {"f:price:min", "f:price:max", "f:back"} <= data
    assert "f:reset:menu" not in data  # nothing to reset yet

    await harness.tap("f:back")
    assert "Listings" in harness.session.of(EditMessageText)[-1].text


async def test_sort_cheapest_reorders_cards_and_is_shown_as_active(harness: Harness) -> None:
    await searched(harness)
    await harness.tap("f:sort:cheapest")
    menu = harness.session.of(EditMessageText)[-1]
    assert "Sort: Cheapest" in menu.text
    assert "f:reset:menu" in harness.session.buttons(menu)

    await harness.tap("f:back")
    results = harness.session.of(EditMessageText)[-1]
    assert cards(results.text)[0] == "Айфон 13"  # the 380 EUR one is the cheapest
    assert "Filters:" in results.text and "Cheapest" in results.text
    assert "f:reset" in harness.session.buttons(results)


async def test_source_filter_recomputes_counts_and_stats_without_refetching(
    harness: Harness,
) -> None:
    await searched(harness)
    sources = harness.services.search._orchestrator._sources  # type: ignore[attr-defined]
    calls_before = [len(s.calls) for s in sources]

    await harness.tap("f:src:telegram")
    await harness.tap("f:back")
    text = harness.session.of(EditMessageText)[-1].text
    assert "Telegram 1" in text and "Bazaraki 0" in text
    assert "showing 1 of 8" in text
    assert cards(text) == ["Айфон 13"]

    assert [len(s.calls) for s in sources] == calls_before


async def test_typed_price_updates_the_filters_message_in_place(harness: Harness) -> None:
    await searched(harness)
    await harness.tap("f:menu")
    await harness.tap("f:price:min")
    assert "minimum" in harness.session.of(EditMessageText)[-1].text
    anchor = harness.last_host_id
    sent_before = len(harness.session.of(SendMessage))

    await harness.say("420")

    edit = harness.session.of(EditMessageText)[-1]
    assert edit.message_id == anchor  # the same message, not a new one
    assert len(harness.session.of(SendMessage)) == sent_before
    assert "from €420" in edit.text and "5 of 8" in edit.text
    labels = [b.text for row in edit.reply_markup.inline_keyboard for b in row]
    assert "Min price: €420" in labels

    await harness.tap("f:back")
    text = harness.session.of(EditMessageText)[-1].text
    assert len(cards(text)) == 5
    assert "Min €420" in text  # stats were recomputed for the filtered subset


async def test_a_price_is_only_expected_once_after_the_prompt(harness: Harness) -> None:
    await searched(harness)
    await harness.tap("f:price:min")
    await harness.say("420")
    session = await harness.sessions.get(USER_ID)
    assert session is not None and session.pending_price is None

    sent_before = len(harness.session.of(SendMessage))
    await harness.say("13")  # no longer a price: a plain search for "13"
    assert len(harness.session.of(SendMessage)) == sent_before + 1
    assert "Searching" in harness.session.of(SendMessage)[-1].text
    fresh = await harness.sessions.get(USER_ID)
    assert fresh is not None and fresh.filters.is_default


async def test_price_range_and_clearing(harness: Harness) -> None:
    await searched(harness)
    await harness.tap("f:price:max")
    await harness.say("300")
    await harness.tap("f:price:min")
    await harness.say("400")  # min above max
    assert "can't be higher" in harness.session.of(SendMessage)[-1].text

    await harness.say("200")  # still waiting for the min: a valid number is accepted
    assert "€200 – €300" in harness.session.of(EditMessageText)[-1].text

    await harness.tap("f:price:max")
    await harness.say("0")  # 0 clears the bound
    assert "from €200" in harness.session.of(EditMessageText)[-1].text


async def test_a_new_product_name_while_waiting_for_a_price_is_a_normal_search(
    harness: Harness,
) -> None:
    await searched(harness)
    await harness.tap("f:price:min")
    await harness.say("iphone 13")  # not a number

    assert "Searching" in harness.session.of(SendMessage)[-1].text
    assert "Listings" in harness.session.of(EditMessageText)[-1].text
    session = await harness.sessions.get(USER_ID)
    assert session is not None
    assert session.pending_price is None and session.filters.is_default


async def test_filters_that_match_nothing_keep_reset_reachable(harness: Harness) -> None:
    await searched(harness)
    await harness.tap("f:price:min")
    await harness.say("5000")
    await harness.tap("f:back")

    last = harness.session.of(EditMessageText)[-1]
    assert "No listings match your filters" in last.text and "8 found" in last.text
    assert {"f:menu", "f:reset"} <= set(harness.session.buttons(last))

    await harness.tap("f:reset")
    restored = harness.session.of(EditMessageText)[-1]
    assert "Listings" in restored.text and "Filters:" not in restored.text


async def test_reset_from_the_menu_stays_in_the_menu(harness: Harness) -> None:
    await searched(harness)
    await harness.tap("f:sort:cheapest")
    await harness.tap("f:src:bazaraki")
    await harness.tap("f:reset:menu")
    menu = harness.session.of(EditMessageText)[-1]
    assert "Price: any" in menu.text and "Sort: Newest" in menu.text
    assert "8 of 8" in menu.text


async def test_filter_changes_return_to_the_first_page(harness: Harness) -> None:
    await searched(harness)
    await harness.tap("pg:1")
    await harness.tap("f:sort:cheapest")
    await harness.tap("f:back")
    assert "page 1/2" in harness.session.of(EditMessageText)[-1].text


async def test_paging_keeps_the_active_filters(harness: Harness) -> None:
    await searched(harness)
    await harness.tap("f:sort:cheapest")
    await harness.tap("f:back")
    await harness.tap("pg:1")
    text = harness.session.of(EditMessageText)[-1].text
    assert "page 2/2" in text and "Filters:" in text


async def test_forged_stale_and_expired_filter_callbacks_are_harmless(harness: Harness) -> None:
    await harness.tap("f:menu")  # no search yet -> no session
    assert "expired" in (harness.session.of(AnswerCallbackQuery)[-1].text or "")

    await searched(harness)
    edits_before = len(harness.session.of(EditMessageText))
    for data in ("f:bogus", "f:src:atlantis", "f:sort:random", "f:price:avg", "f:"):
        await harness.tap(data)
    assert len(harness.session.of(EditMessageText)) == edits_before


async def test_filters_menu_in_russian() -> None:
    h = Harness(sources_with_listings(), settings())
    await h.say("/start", lang="ru")
    await h.tap("lang:ru", lang="ru")
    await h.tap("city:limassol", lang="ru")
    await h.say("iphone 13", lang="ru")
    await h.tap("f:sort:cheapest", lang="ru")
    text = h.session.of(EditMessageText)[-1].text
    assert "Фильтры" in text and "Сортировка: Сначала дешёвые" in text
    assert "Подходит объявлений: 8 из 8" in text


async def test_messages_without_text_get_a_friendly_reply(harness: Harness) -> None:
    await onboard(harness)
    await harness.send_without_text()
    assert "only read text" in harness.session.of(SendMessage)[-1].text
