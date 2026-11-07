"""The neighbourhood ("area") filter: parsing it from Bazaraki, filtering, and the picker."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from aiogram.methods import EditMessageText

from aggregator.domain.models import Filters, Listing
from aggregator.search.filters import build_view
from aggregator.services.filters import FilterError, set_area
from aggregator.sources.bazaraki.parser import area_from_location, parse_search_page
from factories import make_listing
from test_bot_flow import Harness, onboard, settings
from test_categories import advert, page
from test_orchestrator import FakeSource

# --- reading the area from Bazaraki's location text -----------------------------------------


@pytest.mark.parametrize(
    ("location", "area"),
    [
        ("Limassol — Limassol - Agia Zoni", "Agia Zoni"),
        ("Limassol — Germasogeia Tourist Area", "Germasogeia"),  # Bazaraki's suffix is dropped
        ("Limassol — Potamos Germasogeias", "Potamos Germasogeias"),
        ("Nicosia — Nicosia - Strovolos", "Strovolos"),
        ("Larnaca — Larnaka - Mackenzie", "Mackenzie"),
        ("  Limassol   —   Limassol - Zakaki ", "Zakaki"),  # stray spaces
        # Real neighbourhoods that the city lookup also knows: they must be kept.
        ("Limassol — Germasogeia", "Germasogeia"),
        ("Famagusta — Protaras", "Protaras"),
        ("Larnaca — Oroklini", "Oroklini"),
        ("Nicosia — Egkomi", "Egkomi"),
        ("Nicosia — Lakatameia - Synoikismos Anthoupolis", "Lakatameia - Synoikismos Anthoupolis"),
        ("Limassol", None),  # only the city
        ("Limassol — Limassol", None),
        ("", None),
        (None, None),
    ],
)
def test_area_from_location(location: str | None, area: str | None) -> None:
    assert area_from_location(location) == area


def test_listings_carry_their_area() -> None:
    html = page(
        [
            advert(1, "Flat", 1500, ["real-estate-to-rent"], "Limassol — Limassol - Agia Zoni"),
            advert(2, "Flat", 1600, ["real-estate-to-rent"], "Limassol"),
        ]
    )
    listings = parse_search_page(html, now=datetime(2026, 11, 7, tzinfo=UTC)).listings
    assert [li.area for li in listings] == ["Agia Zoni", None]


# --- filtering ------------------------------------------------------------------------------


def flats() -> list[Listing]:
    rows = [
        ("Agia Zoni", 1500),
        ("Agia Zoni", 1600),
        ("Agia Zoni", 1700),
        ("Zakaki", 1400),
        ("Zakaki", 1450),
        ("Neapolis", 1800),
    ]
    listings = [
        make_listing(f"Flat {i}", price=price, external_id=f"b{i}", area=area)
        for i, (area, price) in enumerate(rows)
    ]
    listings.append(
        make_listing("Flat from a post", price=1500, source="telegram", external_id="t")
    )
    return listings


def test_the_view_lists_areas_most_listings_first_then_alphabetically() -> None:
    view = build_view(flats(), Filters())
    assert view.areas == [("Agia Zoni", 3), ("Zakaki", 2), ("Neapolis", 1)]
    assert len(view.listings) == 7  # no area chosen: nothing is excluded


def test_choosing_an_area_keeps_only_that_area() -> None:
    view = build_view(flats(), Filters(area="Zakaki"))
    assert {li.area for li in view.listings} == {"Zakaki"} and len(view.listings) == 2
    assert view.stats.priced_count == 2
    assert view.areas == [("Agia Zoni", 3), ("Zakaki", 2), ("Neapolis", 1)]  # picker keeps all


def test_listings_without_an_area_are_excluded_while_one_is_chosen() -> None:
    view = build_view(flats(), Filters(area="Agia Zoni"))
    assert all(li.source == "bazaraki" for li in view.listings)


def test_area_counts_follow_the_other_filters() -> None:
    view = build_view(flats(), Filters(min_price=Decimal(1500)))
    assert view.areas == [("Agia Zoni", 3), ("Neapolis", 1)]  # Zakaki is all below 1500
    assert build_view(flats(), Filters(source="telegram")).areas == []


def test_hidden_unusual_listings_are_not_counted_in_the_picker() -> None:
    listings = [
        *(
            make_listing(f"Phone {i}", price=300 + i, external_id=f"p{i}", area="Marina")
            for i in range(8)
        ),
        make_listing("Case", price=3, external_id="junk", area="Zakaki"),
    ]
    assert build_view(listings, Filters()).areas == [("Marina", 8)]
    shown = build_view(listings, Filters(show_unusual_prices=True))
    assert shown.areas == [("Marina", 8), ("Zakaki", 1)]


def test_an_area_is_part_of_the_filters_state() -> None:
    assert Filters().is_default
    assert not Filters(area="Zakaki").is_default


def test_set_area_validates() -> None:
    assert set_area(Filters(), "Zakaki", ["Zakaki"]).area == "Zakaki"
    assert set_area(Filters(area="Zakaki"), None, ["Zakaki"]).area is None
    with pytest.raises(FilterError):
        set_area(Filters(), "Atlantis", ["Zakaki"])


# --- the dialogue ---------------------------------------------------------------------------


def bazaraki_flats() -> Harness:
    areas = ["Agia Zoni"] * 4 + ["Zakaki"] * 2 + ["Neapolis"]
    listings = [
        make_listing(
            f"3 bedroom apartment {i}", price=1500 + i * 10, external_id=f"b{i}", area=area
        )
        for i, area in enumerate(areas)
    ]
    return Harness([FakeSource("bazaraki", listings)], settings())


def labels(call: Any) -> list[str]:
    return [b.text for row in call.reply_markup.inline_keyboard for b in row]


def data(call: Any) -> list[str]:
    return [b.callback_data for row in call.reply_markup.inline_keyboard for b in row]


def cards(text: str) -> list[str]:
    return re.findall(r'^\d+\. <a href="[^"]+">([^<]+)</a>', text, flags=re.MULTILINE)


async def test_the_area_picker_filters_the_results() -> None:
    h = bazaraki_flats()
    await onboard(h)
    await h.say("3 bedroom apartment")
    await h.tap("f:menu")
    menu = h.session.of(EditMessageText)[-1]
    assert "Area: any" in menu.text and "📍 Area" in labels(menu) and "f:area" in data(menu)

    await h.tap("f:area")
    picker = h.session.of(EditMessageText)[-1]
    assert "Choose an area" in picker.text
    assert labels(picker) == ["Agia Zoni (4)", "Zakaki (2)", "Neapolis (1)", "All areas", "Cancel"]
    assert data(picker) == ["f:area:0", "f:area:1", "f:area:2", "f:area:all", "f:menu"]

    await h.tap("f:area:1")  # Zakaki
    menu = h.session.of(EditMessageText)[-1]
    assert "Area: Zakaki" in menu.text and "2 of 7" in menu.text
    assert "📍 Area: Zakaki" in labels(menu)

    await h.tap("f:back")
    text = h.session.of(EditMessageText)[-1].text
    assert len(cards(text)) == 2 and "Zakaki" in text.split("Listings")[0]  # the Filters: line

    await h.tap("f:reset")
    assert "Filters:" not in h.session.of(EditMessageText)[-1].text


async def test_all_areas_clears_the_choice() -> None:
    h = bazaraki_flats()
    await onboard(h)
    await h.say("3 bedroom apartment")
    await h.tap("f:area:0")
    assert "Area: Agia Zoni" in h.session.of(EditMessageText)[-1].text
    await h.tap("f:area:all")
    assert "Area: any" in h.session.of(EditMessageText)[-1].text


@pytest.mark.parametrize("forged", ["f:area:9", "f:area:abc", "f:area:-1x", "f:area:"])
async def test_forged_area_taps_change_nothing(forged: str) -> None:
    h = bazaraki_flats()
    await onboard(h)
    await h.say("3 bedroom apartment")
    edits = len(h.session.of(EditMessageText))
    await h.tap(forged)
    assert len(h.session.of(EditMessageText)) == edits


async def test_results_without_any_area_say_so() -> None:
    listings = [
        make_listing(f"3 bedroom apartment {i}", price=1500, external_id=f"t{i}", source="telegram")
        for i in range(3)
    ]
    h = Harness([FakeSource("telegram", listings)], settings())
    await onboard(h)
    await h.say("3 bedroom apartment")
    await h.tap("f:area")
    picker = h.session.of(EditMessageText)[-1]
    assert "no area information" in picker.text
    assert labels(picker) == ["All areas", "Cancel"]


async def test_area_names_are_html_escaped() -> None:
    listing = make_listing("3 bedroom apartment", price=1500, external_id="x", area="A <b>&</b> B")
    h = Harness([FakeSource("bazaraki", [listing])], settings())
    await onboard(h)
    await h.say("3 bedroom apartment")
    await h.tap("f:area:0")
    assert "A &lt;b&gt;&amp;&lt;/b&gt; B" in h.session.of(EditMessageText)[-1].text


async def test_the_area_picker_in_russian() -> None:
    h = bazaraki_flats()
    await h.say("/start", lang="ru")
    await h.tap("lang:ru", lang="ru")
    await h.tap("city:limassol", lang="ru")
    await h.say("3 bedroom apartment", lang="ru")
    await h.tap("f:area", lang="ru")
    picker = h.session.of(EditMessageText)[-1]
    assert "Выберите район" in picker.text and "Все районы" in labels(picker)
    await h.tap("f:area:0", lang="ru")
    assert "Район: Agia Zoni" in h.session.of(EditMessageText)[-1].text
