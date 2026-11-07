"""Cities and neighbourhoods written in many ways: case, spelling, case endings, transliteration."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from aggregator.db.models import Listing as ListingRow
from aggregator.db.repositories import _to_domain
from aggregator.domain.areas import AREAS, canonical_area, detect_area, fold_spelling, locate
from aggregator.domain.cities import City, detect_city
from aggregator.domain.lexicon import canonical_token
from aggregator.query import expand_with_rules
from aggregator.search.relevance import filter_relevant, tokenize
from aggregator.sources.telegram.parser import parse_message
from factories import make_listing

# --- spelling variants of the same place ----------------------------------------------------


@pytest.mark.parametrize(
    ("text", "area"),
    [
        # Germasogeia: the many Russian and Latin spellings, in any case
        ("Лимассол, Гермасойя", "Germasogeia"),
        ("лимассол гермасойя", "Germasogeia"),
        ("ЛИМАССОЛ ГЕРМАСОЙЯ", "Germasogeia"),
        ("Лимассол, Гермассоя", "Germasogeia"),  # doubled "с" is ignored
        ("Гермасоя", "Germasogeia"),
        ("Yermasoyia", "Germasogeia"),
        ("GERMASOGEIA", "Germasogeia"),
        ("Germasogeia Tourist Area", "Germasogeia"),
        # Russian case endings
        ("Продаю в Гермасойе", "Germasogeia"),
        ("Самовывоз из Гермасойи", "Germasogeia"),
        ("Живу в Строволосе", "Strovolos"),
        ("рядом с Неаполисом", "Neapolis"),
        # hyphens, dots, extra spaces, capital letters mid-word
        ("Айя-Напа", "Ayia Napa"),
        ("Айя  Напа", "Ayia Napa"),
        ("📍Айия Напа", "Ayia Napa"),
        ("AYIA-NAPA", "Ayia Napa"),
        ("Агиос Тихонас", "Agios Tychon"),
        ("АЙОС ТИХОНАС", "Agios Tychon"),
        ("Агия Зони", "Agia Zoni"),
        ("Агиа Зони", "Agia Zoni"),
        ("Агиос Афанасиос, Лимассол", "Agios Athanasios"),
        # spellings taken from real posts
        ("Колоси Лимасол", "Kolossi"),
        ("Колосси", "Kolossi"),
        ("Ипсонас", "Ypsonas"),
        ("Писсури", "Pissouri"),
        ("Пиргос Лимасол", "Pyrgos"),
        ("ЛИМАСОЛ/НЕАПОЛИС (КАНИКА)", "Neapolis"),
        # other districts
        ("Ларнака, Маккензи", "Mackenzie"),
        ("Като Пафос", "Kato Paphos"),
        ("Корал Бэй", "Coral Bay"),
        ("Протарас", "Protaras"),
        ("Энгоми, Никосия", "Egkomi"),
        ("Лакатамия", "Lakatamia"),
    ],
)
def test_detect_area(text: str, area: str) -> None:
    found = detect_area(text)
    assert found is not None and found.name == area, text


@pytest.mark.parametrize(
    "text",
    [
        "талант",  # "тала" must not match a longer word
        "страховой полис",
        "колосок пшеницы",  # a stem + ending must not swallow unrelated words
        "Just a nice chair",
        "",
        "Лимассол",  # a city is not a neighbourhood
        "Limassol, Cyprus",
    ],
)
def test_no_area_where_there_is_none(text: str) -> None:
    assert detect_area(text) is None


def test_the_first_mention_wins_and_the_longest_name_on_a_tie() -> None:
    assert detect_area("Неаполис, доставка в Закаки").name == "Neapolis"  # type: ignore[union-attr]
    assert detect_area("Kato Polemidia").name == "Kato Polemidia"  # type: ignore[union-attr]
    assert detect_area("Potamos Germasogeias").name == "Potamos Germasogeias"  # type: ignore[union-attr]


def test_fold_spelling() -> None:
    assert fold_spelling("  Айя-Напа ") == "айя напа"
    assert fold_spelling("Лимассол") == fold_spelling("Лимасол")
    assert fold_spelling("Ёлка") == "елка"


# --- cities ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "city"),
    [
        ("Никозия", City.NICOSIA),
        ("в никозии", City.NICOSIA),
        ("НИКОЗИЮ", City.NICOSIA),
        ("Лефкоза", City.NICOSIA),
        ("Левкосия", City.NICOSIA),
        ("Лемесо", City.LIMASSOL),
        ("ЛИМАССОЛЬ", City.LIMASSOL),
        ("лимасол", City.LIMASSOL),
        ("Аммохостос", City.FAMAGUSTA),
        ("Фамагуста", City.FAMAGUSTA),
        ("Ларнака", City.LARNACA),
    ],
)
def test_more_spellings_of_the_city_names(text: str, city: City) -> None:
    assert detect_city(text) is city


def test_an_area_alone_tells_the_city() -> None:
    assert locate("Диван, самовывоз Ипсонас", detect_city("Диван, самовывоз Ипсонас")) == (
        City.LIMASSOL,
        "Ypsonas",
    )
    assert locate("Протарас", detect_city("Протарас"))[0] is City.FAMAGUSTA
    assert locate("Просто диван", City.UNKNOWN) == (City.UNKNOWN, None)


def test_an_area_of_another_city_is_dropped_not_trusted() -> None:
    # City named first; the area belongs to Nicosia, so it cannot be this listing's area.
    text = "Продам в Лимассоле, могу довезти в Строволос"
    assert locate(text, detect_city(text)) == (City.LIMASSOL, None)


def test_a_known_city_and_its_own_area() -> None:
    text = "Лимассол, Гермасойя"
    assert locate(text, detect_city(text)) == (City.LIMASSOL, "Germasogeia")


# --- Bazaraki's own area names ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Germasogeia Tourist Area", "Germasogeia"),
        ("Agios Tychon Tourist Area", "Agios Tychon"),
        ("Germasogeia", "Germasogeia"),
        ("Potamos Germasogeias", "Potamos Germasogeias"),
        ("Agia Zoni", "Agia Zoni"),
        ("Lakatameia - Synoikismos Anthoupolis", "Lakatameia - Synoikismos Anthoupolis"),  # kept
        ("Some Village", "Some Village"),
        (None, None),
        ("", None),
    ],
)
def test_canonical_area(name: str | None, expected: str | None) -> None:
    assert canonical_area(name) == expected


# --- the catalog itself ---------------------------------------------------------------------


def test_the_catalog_is_consistent() -> None:
    seen: dict[str, str] = {}
    for area in AREAS:
        assert area.city in {
            City.NICOSIA,
            City.LIMASSOL,
            City.LARNACA,
            City.PAPHOS,
            City.FAMAGUSTA,
        }
        for name in (area.name, *area.aliases):
            folded = fold_spelling(name)
            assert folded, area.name
            # no word may mix Latin and Cyrillic letters (a typing slip that never matches)
            for word in folded.split():
                assert not (
                    any("a" <= c <= "z" for c in word) and any("а" <= c <= "я" for c in word)
                ), (
                    area.name,
                    word,
                )
            owner = seen.setdefault(folded, area.name)
            assert owner == area.name, f"{name!r} is claimed by {owner!r} and {area.name!r}"


# --- searching with these names --------------------------------------------------------------


def test_one_neighbourhood_in_any_spelling_is_the_same_token() -> None:
    assert canonical_token("гермасойя") == canonical_token("yermasoyia") == "germasogeia"
    assert tokenize("Гермасойя") == tokenize("Yermasoyia") == ["germasogeia"]


def test_a_russian_query_finds_an_english_listing_in_the_same_area() -> None:
    query = expand_with_rules("квартира Гермасойя")
    keep = filter_relevant(
        [
            make_listing("Apartment in Germasogeia", external_id="a"),
            make_listing("Apartment in Mesa Geitonia", external_id="b"),
        ],
        query,
    )
    assert [li.external_id for li in keep] == ["a"]


# --- where it is used ------------------------------------------------------------------------


def test_the_telegram_parser_reads_city_and_area() -> None:
    parsed = parse_message("Продам диван 100€\nЛимассол, Гермасойя")
    assert (parsed.city, parsed.area) == (City.LIMASSOL, "Germasogeia")
    only_area = parse_message("Продам велосипед 80€ Ипсонас")
    assert (only_area.city, only_area.area) == (City.LIMASSOL, "Ypsonas")
    assert parse_message("Продам велосипед 80€").area is None


def test_stored_listings_get_their_area_when_read_back() -> None:
    row = ListingRow(
        source="telegram",
        external_id="1",
        url="https://t.me/x/1",
        title="Диван",
        description="Лимассол, в Гермасойе, самовывоз",
        price_amount=Decimal(100),
        currency="EUR",
        city="limassol",
        posted_at=datetime(2026, 11, 1, tzinfo=UTC),
    )
    assert _to_domain(row).area == "Germasogeia"
    row.description = "Лимассол"
    assert _to_domain(row).area is None
