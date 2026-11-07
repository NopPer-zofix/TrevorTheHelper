"""English / Russian equivalence: the lexicon, room counts, query expansion and matching.

The anchor case: "3-х комнатная квартира" and "3-bedroom apartment" must find the same listings.
"""

from __future__ import annotations

import pytest

from aggregator.domain.cities import City
from aggregator.domain.lexicon import (
    CANONICAL,
    GROUPS,
    canonical_token,
    category_of,
    fold,
    normalize_rooms,
)
from aggregator.domain.models import ExpandedQuery
from aggregator.query import expand_with_rules
from aggregator.search.category_choice import intent_of
from aggregator.search.relevance import filter_relevant, tokenize
from aggregator.sources.base import search_terms
from factories import make_listing

# --- the vocabulary ------------------------------------------------------------------------


def test_every_form_is_lowercase_without_yo_and_belongs_to_one_group() -> None:
    seen: dict[str, str] = {}
    for _, forms in GROUPS:
        for form in forms:
            assert form == fold(form), form
            assert form not in seen or seen[form] == forms[0], f"{form!r} is in two groups"
            seen[form] = forms[0]
    assert len(CANONICAL) == len(seen)


@pytest.mark.parametrize(
    ("word", "canonical"),
    [
        ("flat", "apartment"),
        ("flats", "apartment"),
        ("квартира", "apartment"),
        ("квартирами", "apartment"),  # regular inflection of a known stem
        ("апартаменты", "apartment"),
        ("дом", "house"),
        ("доме", "house"),
        ("вилла", "villa"),
        ("айфон", "iphone"),
        ("велосипеды", "bike"),  # plural
        ("bikes", "bike"),
        ("bicycle", "bike"),
        ("лимассол", "limassol"),
        ("ларнака", "larnaca"),
        ("спальни", "bedroom"),
        ("bedrooms", "bedroom"),
        ("3br", "3br"),  # tokenisation splits it first; the lexicon only sees words
    ],
)
def test_canonical_token(word: str, canonical: str) -> None:
    assert canonical_token(word) == canonical


@pytest.mark.parametrize(
    "word", ["домофон", "часов", "стола-куртка", "table-top", "flatten", "bikini"]
)
def test_look_alike_words_are_not_swallowed(word: str) -> None:
    assert canonical_token(word) == word


def test_category_of() -> None:
    assert category_of("квартира") == "property"
    assert category_of("аренда") == "intent"
    assert category_of("limassol") == "place"
    assert category_of("banana") is None


# --- room counts ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "3-bedroom apartment",
        "3 bedroom apartment",
        "3 bedrooms apartment",
        "3BR apartment",
        "3 bdr apartment",
        "three bedroom apartment",
        "three-bedroom apartment",
        "3 bed apartment",
        "3-х комнатная квартира",
        "3-комнатная квартира",
        "3х комнатная квартира",
        "3 комнатная квартира",
        "3 комнаты квартира",
        "3-х комн. квартира",
        "Трёхкомнатная квартира",
        "трехкомнатная квартира",
        "3 спальни квартира",
        "3-спальная квартира",
        "3к квартира",
    ],
)
def test_every_way_of_writing_three_rooms_becomes_three_bedroom(text: str) -> None:
    assert "3 bedroom" in normalize_rooms(text), text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("двухкомнатная квартира", "2 bedroom"),
        ("2-bedroom flat", "2 bedroom"),
        ("one bedroom apartment", "1 bedroom"),
        ("однокомнатная квартира", "1 bedroom"),
        ("четырёхкомнатная квартира", "4 bedroom"),
    ],
)
def test_other_counts(text: str, expected: str) -> None:
    assert expected in normalize_rooms(text)


def test_digits_that_are_not_room_counts_are_left_alone() -> None:
    assert normalize_rooms("iphone 13 128gb") == "iphone 13 128gb"
    assert normalize_rooms("2 bed sheets") == "2 bed sheets"  # "bed" needs a property word after
    assert "bedroom" not in normalize_rooms("5к евро")
    assert normalize_rooms("flat screen tv") == "flatscreen tv"  # not an apartment


# --- the expansion -------------------------------------------------------------------------


def test_russian_and_english_phrasings_expand_to_the_same_primary_search() -> None:
    ru = expand_with_rules("3-х комнатная квартира")
    en = expand_with_rules("3-bedroom apartment")
    assert ru.normalized == en.normalized == "3 bedroom apartment"
    assert set(ru.variants) == set(en.variants)
    assert "3 bedroom flat" in en.variants and "3-комнатная квартира" in en.variants
    assert ru.original == "3-х комнатная квартира"  # what the user typed is kept for display


def test_search_terms_cover_both_languages_even_with_a_two_term_cap() -> None:
    terms = search_terms(expand_with_rules("3-х комнатная квартира"), 2)
    assert terms == ["3 bedroom apartment", "3-комнатная квартира"]  # not "flat" as the 2nd


def test_the_other_language_comes_second_for_russian_primaries_too() -> None:
    query = ExpandedQuery(
        original="x", normalized="айфон 13", variants=["iphone 13", "iphone13", "айфон13"]
    )
    assert search_terms(query, 2) == ["айфон 13", "iphone 13"]
    assert search_terms(query, 3) == ["айфон 13", "iphone 13", "iphone13"]
    assert search_terms(query, 10)[:4] == ["айфон 13", "iphone 13", "iphone13", "айфон13"]


def test_rent_and_sale_words_are_intent_not_search_text() -> None:
    for text in ("3 bedroom apartment for rent", "3-х комнатная квартира аренда", "квартира сдам"):
        assert "rent" not in expand_with_rules(text).normalized
        assert "аренда" not in expand_with_rules(text).normalized
    assert intent_of("3-х комнатная квартира аренда") == "rent"


def test_places_are_translated_and_other_words_kept() -> None:
    ru = expand_with_rules("2-х комнатная квартира лимассол вид на море")
    assert ru.normalized == "2 bedroom apartment limassol вид море"
    assert "2-комнатная квартира лимассол вид море" in ru.variants
    en = expand_with_rules("2 bedroom flat limassol")
    assert "2-комнатная квартира лимассол" in en.variants


def test_kinds_of_property() -> None:
    assert expand_with_rules("дом 4 спальни").normalized == "4 bedroom house"
    assert "дом 4 спальни" in expand_with_rules("4 bedroom house").variants
    assert expand_with_rules("вилла с бассейном").normalized.startswith("villa")
    assert expand_with_rules("студия").normalized == "studio"
    assert "студия" in expand_with_rules("studio").variants
    assert expand_with_rules("apartment").normalized == "apartment"  # no room count: fine


def test_non_property_queries_keep_their_old_behaviour() -> None:
    q = expand_with_rules("iphone 13 128gb")
    assert q.normalized == "iphone 13 128gb" and q.category_hint == "phone"
    assert "айфон 13 128gb" in q.variants
    bike = expand_with_rules("велосипед горный 26")
    assert bike.normalized == "велосипед горный 26" and bike.category_hint == "bike"


# --- matching: the user's actual complaint -------------------------------------------------

TITLES_3BR = [
    "3-bedroom apartment to rent in Limassol",
    "3 bedroom flat for rent",
    "3 Bedrooms Apartment, sea view",
    "Spacious 3BR flat Germasogeia",
    "Трехкомнатная квартира в аренду, Лимассол",
    "3-х комнатная квартира, центр",
    "Квартира 3 спальни, Лимассол",
    "3-комнатная квартира сдаётся",
]
TITLES_OTHER = [
    "2-bedroom apartment to rent",
    "2-х комнатная квартира",
    "3 bedroom house for sale",
    "Дом 3 спальни",
    "4 bedroom apartment",
    "Iphone 13 128gb",
]


def keep(query: ExpandedQuery, titles: list[str]) -> list[str]:
    listings = [make_listing(t, price=1000, external_id=str(i)) for i, t in enumerate(titles)]
    return [li.title for li in filter_relevant(listings, query)]


@pytest.mark.parametrize("text", ["3-х комнатная квартира", "3-bedroom apartment", "3 bed flat"])
def test_both_languages_find_the_same_listings_in_both_languages(text: str) -> None:
    query = expand_with_rules(text)
    assert keep(query, TITLES_3BR + TITLES_OTHER) == TITLES_3BR


def test_a_different_room_count_or_kind_of_property_is_not_a_match() -> None:
    query = expand_with_rules("3-х комнатная квартира")
    assert keep(query, TITLES_OTHER) == []


def test_the_same_holds_for_other_word_pairs() -> None:
    iphone = expand_with_rules("айфон 13")
    assert keep(iphone, ["iPhone 13 128GB", "Apple iphone13", "Айфоны 13", "iPhone 12"]) == [
        "iPhone 13 128GB",
        "Apple iphone13",
        "Айфоны 13",
    ]
    bikes = expand_with_rules("bicycle")
    assert keep(bikes, ["Велосипеды горные", "Bikes for kids", "Скутер"]) == [
        "Велосипеды горные",
        "Bikes for kids",
    ]


def test_tokens_are_language_neutral() -> None:
    assert (
        tokenize("3-х комнатная квартира")
        == tokenize("3 bedroom flat")
        == ["3", "bedroom", "apartment"]
    )
    assert tokenize("Лимассол") == tokenize("LIMASSOL") == ["limassol"]


def test_city_is_unaffected() -> None:
    assert City.LIMASSOL.value == "limassol"
