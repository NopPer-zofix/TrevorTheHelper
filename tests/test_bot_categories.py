"""The category question dialogue ("rent or buy? flat or house?") through the real dispatcher."""

from __future__ import annotations

from typing import Any

import pytest
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage

from aggregator.domain.cities import City
from aggregator.domain.models import ExpandedQuery, Filters, Listing
from aggregator.sources.base import SourceError
from factories import make_listing
from test_bot_flow import Harness, onboard, settings
from test_orchestrator import FakeSource

PHONES = "telephones/mobile-phones"
RENT_FLATS = "real-estate-to-rent/apartments-flats"
RENT_HOUSES = "real-estate-to-rent/houses"
SALE_FLATS = "real-estate-for-sale/apartments-flats"

# What the first (unscoped) results page looks like for "3 bedroom apartment".
PROPERTY_SAMPLE = {SALE_FLATS: 30, "real-estate-for-sale/houses": 8, RENT_FLATS: 12, RENT_HOUSES: 4}


class CategorySource(FakeSource):
    """A Bazaraki stand-in: knows its categories, explores them, and honours a category scope."""

    def __init__(self, listings: list[Listing], samples: dict[str, Any]) -> None:
        super().__init__("bazaraki", listings)
        self.samples = samples  # normalized query -> counts (or an exception to raise)

    async def explore_categories(self, query: ExpandedQuery, city: City | None) -> dict[str, int]:
        sample = self.samples.get(query.normalized, self.samples.get("*", {}))
        if isinstance(sample, Exception):
            raise sample
        return sample  # type: ignore[no-any-return]

    async def search(
        self, query: ExpandedQuery, city: City | None, filters: Filters
    ) -> list[Listing]:
        found = await super().search(query, city, filters)
        if filters.category:
            found = [li for li in found if (li.category or "").startswith(filters.category)]
        return found


def flat(i: int, category: str, price: int, kind: str) -> Listing:
    return make_listing(
        f"3 bedroom apartment {kind} #{i}",
        price=price,
        external_id=f"{category}-{i}",
        category=category,
    )


def property_listings() -> list[Listing]:
    return [
        *(flat(i, RENT_FLATS, 1500 + i * 50, "to rent") for i in range(6)),
        *(flat(i, RENT_HOUSES, 2500 + i * 50, "house to rent") for i in range(2)),
        *(flat(i, SALE_FLATS, 210_000 + i * 5000, "for sale") for i in range(4)),
    ]


def phone_listings() -> list[Listing]:
    return [
        *(
            make_listing(
                f"iPhone 13 128GB #{i}", price=300 + i * 10, external_id=f"p{i}", category=PHONES
            )
            for i in range(6)
        ),
        make_listing(
            "Charger for iphone 13 lot",
            price=5,
            external_id="acc",
            category="telephones/accessories",
        ),
    ]


def make_harness(samples: dict[str, Any]) -> tuple[Harness, CategorySource]:
    source = CategorySource([*property_listings(), *phone_listings()], samples)
    return Harness([source], settings()), source


def labels(call: Any) -> list[str]:
    return [b.text for row in call.reply_markup.inline_keyboard for b in row]


def data(call: Any) -> list[str]:
    return [b.callback_data for row in call.reply_markup.inline_keyboard for b in row]


async def asked(h: Harness, text: str = "3 bedroom apartment") -> Any:
    await onboard(h)
    await h.say(text)
    return h.session.of(EditMessageText)[-1]


# --- when no question is needed ------------------------------------------------------------


async def test_a_dominant_category_is_used_without_asking() -> None:
    h, source = make_harness({"iphone 13": {PHONES: 40, "telephones/accessories": 3}})
    await onboard(h)
    sent_before = len(h.session.of(SendMessage))
    await h.say("iphone 13")

    assert len(h.session.of(SendMessage)) == sent_before + 1  # only the progress message
    assert source.calls[-1][2].category == PHONES
    result = h.session.of(EditMessageText)[-1].text
    assert "Category: Mobile phones, communication › Mobile phones" in result
    assert "Charger" not in result and "Listings" in result


async def test_no_evidence_means_a_plain_search() -> None:
    h, source = make_harness({})  # the explorer reports nothing
    await onboard(h)
    await h.say("iphone 13")
    assert source.calls[-1][2].category is None
    assert "Category:" not in h.session.of(EditMessageText)[-1].text


async def test_a_failing_explorer_never_blocks_the_search() -> None:
    h, source = make_harness({"iphone 13": SourceError("blocked")})
    await onboard(h)
    await h.say("iphone 13")
    assert source.calls[-1][2].category is None
    assert "Listings" in h.session.of(EditMessageText)[-1].text


# --- asking --------------------------------------------------------------------------------


async def test_an_ambiguous_search_asks_which_kind_of_listing() -> None:
    h, source = make_harness({"3 bedroom apartment": PROPERTY_SAMPLE})
    await onboard(h)
    sent_before = len(h.session.of(SendMessage))
    await h.say("3 bedroom apartment")

    assert (
        len(h.session.of(SendMessage)) == sent_before + 1
    )  # one message, edited into the question
    question = h.session.of(EditMessageText)[-1]
    assert "What are you looking for?" in question.text and "3 bedroom apartment" in question.text
    assert labels(question) == [
        "Real Estate for sale (38)",
        "Real Estate to rent (16)",
        "🔎 Any category",
    ]
    assert data(question) == ["c:0", "c:1", "c:any"]
    assert source.calls == []  # nothing is searched until the user answers


async def test_two_questions_rent_or_buy_then_flat_or_house() -> None:
    h, source = make_harness({"3 bedroom apartment": PROPERTY_SAMPLE})
    await asked(h)

    await h.tap("c:1")  # "Real Estate to rent"
    second = h.session.of(EditMessageText)[-1]
    assert "In: <b>Real Estate to rent</b>" in second.text
    assert labels(second) == ["Apartments, flats (12)", "Houses (4)", "🔎 Any category"]
    assert source.calls == []

    await h.tap("c:0")  # "Apartments, flats"
    assert source.calls[-1][2].category == RENT_FLATS
    result = h.session.of(EditMessageText)[-1]
    assert "Category: Real Estate to rent › Apartments, flats" in result.text
    assert "for sale" not in result.text and "house" not in result.text
    assert "Found 6" in result.text
    assert h.session.of(AnswerCallbackQuery)  # taps were acknowledged


async def test_the_answer_edits_the_question_message_in_place() -> None:
    h, _ = make_harness({"3 bedroom apartment": PROPERTY_SAMPLE})
    await asked(h)
    sent = len(h.session.of(SendMessage))
    await h.tap("c:1")
    await h.tap("c:1")  # houses
    assert len(h.session.of(SendMessage)) == sent  # no new messages, only edits
    assert h.session.of(EditMessageText)[-1].message_id == h.last_host_id


async def test_a_rent_word_skips_the_rent_or_buy_question() -> None:
    h, source = make_harness({"*": PROPERTY_SAMPLE})
    question = await asked(h, "3 bedroom apartment for rent")
    assert "In: <b>Real Estate to rent</b>" in question.text  # straight to flat / house
    assert labels(question)[0].startswith("Apartments, flats")
    assert source.calls == []


async def test_any_category_searches_everywhere() -> None:
    h, source = make_harness({"3 bedroom apartment": PROPERTY_SAMPLE})
    await asked(h)
    await h.tap("c:any")
    assert source.calls[-1][2].category is None
    result = h.session.of(EditMessageText)[-1].text
    assert "Category:" not in result and "Found 12" in result


async def test_the_chosen_category_survives_filters_and_paging() -> None:
    h, _ = make_harness({"3 bedroom apartment": PROPERTY_SAMPLE})
    await asked(h)
    await h.tap("c:1")
    await h.tap("c:0")
    await h.tap("f:sort:cheapest")
    await h.tap("f:back")
    assert (
        "Category: Real Estate to rent › Apartments, flats"
        in h.session.of(EditMessageText)[-1].text
    )


# --- the question's life cycle -------------------------------------------------------------


async def test_answering_after_the_question_expired_is_harmless() -> None:
    h, source = make_harness({})
    await onboard(h)
    await h.tap("c:0")
    assert "expired" in (h.session.of(AnswerCallbackQuery)[-1].text or "")
    assert source.calls == []


@pytest.mark.parametrize("forged", ["c:99", "c:abc", "c:", "c:-1x"])
async def test_forged_answers_are_ignored(forged: str) -> None:
    h, source = make_harness({"3 bedroom apartment": PROPERTY_SAMPLE})
    await asked(h)
    edits = len(h.session.of(EditMessageText))
    await h.tap(forged)
    assert len(h.session.of(EditMessageText)) == edits and source.calls == []
    await h.tap("c:any")  # the real question is still answerable afterwards
    assert source.calls


async def test_a_new_search_replaces_an_unanswered_question() -> None:
    h, source = make_harness({"3 bedroom apartment": PROPERTY_SAMPLE, "iphone 13": {PHONES: 40}})
    await asked(h)
    await h.say("iphone 13")  # resolved without a question
    await h.tap("c:0")  # the old question is gone
    assert "expired" in (h.session.of(AnswerCallbackQuery)[-1].text or "")
    assert source.calls[-1][2].category == PHONES


async def test_each_user_has_their_own_pending_question() -> None:
    h, source = make_harness({"3 bedroom apartment": PROPERTY_SAMPLE})
    await asked(h)
    await h.tap("c:any", user_id=999)  # someone else cannot answer it
    assert source.calls == []


# --- language ------------------------------------------------------------------------------


async def test_the_question_is_asked_in_russian() -> None:
    h, source = make_harness({"3 bedroom apartment": PROPERTY_SAMPLE})
    await h.say("/start", lang="ru")
    await h.tap("lang:ru", lang="ru")
    await h.tap("city:limassol", lang="ru")
    await h.say("3 bedroom apartment", lang="ru")

    question = h.session.of(EditMessageText)[-1]
    assert "Что вы ищете?" in question.text
    assert labels(question) == [
        "Недвижимость: продажа (38)",
        "Недвижимость: аренда (16)",
        "🔎 Любая категория",
    ]
    await h.tap("c:1", lang="ru")
    assert "В разделе: <b>Недвижимость: аренда</b>" in h.session.of(EditMessageText)[-1].text
    await h.tap("c:0", lang="ru")
    assert "Категория: Недвижимость: аренда › Квартиры" in h.session.of(EditMessageText)[-1].text
    assert source.calls[-1][2].category == RENT_FLATS
