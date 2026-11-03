from __future__ import annotations

import pytest

from aggregator.domain.models import ExpandedQuery
from aggregator.query import expand_with_rules
from aggregator.search.relevance import filter_relevant, relevance_score, tokenize
from factories import make_listing


def keeps(query: ExpandedQuery, title: str, description: str | None = None) -> bool:
    listing = make_listing(title, description=description)
    return bool(filter_relevant([listing], query))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("iPhone13 128GB", ["iphone", "13", "128", "gb"]),
        ("Айфон 13 128 ГБ", ["айфон", "13", "128", "gb"]),
        ("Ёлка", ["елка"]),
        ("a + b", ["a", "+", "b"]),
    ],
)
def test_tokenize(text: str, expected: list[str]) -> None:
    assert tokenize(text) == expected


class TestPhoneQuery:
    query = expand_with_rules("iphone 13")

    @pytest.mark.parametrize(
        "title",
        [
            "iPhone 13 128GB Blue",
            "Apple iphone13 like new",
            "Айфон 13 в отличном состоянии",
            "iPhone 13 Pro Max",  # same family: accepted on purpose
            "IPHONES 13 lot",  # plural endings
        ],
    )
    def test_keeps_the_product(self, title: str) -> None:
        assert keeps(self.query, title)

    @pytest.mark.parametrize(
        "title",
        [
            "iPhone 12 64GB",  # numbers must match exactly
            "Samsung Galaxy S21",
            "Чехол для iPhone 13",
            "Case for iPhone 13",
            "iPhone 13 charger cable",
            "Защитное стекло iPhone 13",
        ],
    )
    def test_drops_other_products_and_accessories(self, title: str) -> None:
        assert not keeps(self.query, title)

    @pytest.mark.parametrize(
        "title",
        [
            "iPhone 13 with charger",
            "iPhone 13 + case",
            "iPhone 13 с зарядкой",
            "iPhone 13 case incl",
        ],
    )
    def test_bundled_accessories_do_not_disqualify(self, title: str) -> None:
        assert keeps(self.query, title)

    def test_description_only_match_is_kept_but_scores_lower(self) -> None:
        in_title = make_listing("iPhone 13")
        in_description = make_listing("Phone for sale", description="Apple iPhone 13 like new")
        assert relevance_score(in_description, self.query) < relevance_score(in_title, self.query)
        assert keeps(self.query, "Phone for sale", "Apple iPhone 13 like new")

    def test_negative_terms_ignore_the_description(self) -> None:
        assert keeps(self.query, "iPhone 13", "comes without charger or case")


def test_missing_specs_are_forgiven_but_wrong_models_are_not() -> None:
    query = expand_with_rules("iphone 13 128gb")
    assert keeps(query, "iPhone 13")  # seller omitted storage
    assert keeps(query, "iPhone 13 128 гб")
    assert not keeps(query, "iPhone 12 128GB")


def test_russian_query_with_inflections() -> None:
    query = expand_with_rules("велосипед горный 26")
    assert keeps(query, "Горный велосипед 26 дюймов")
    assert keeps(query, "Продам велосипеды горные 26")
    assert not keeps(query, "Детский велосипед 16")
    assert not keeps(query, "Шлем для велосипеда")  # accessory


def test_a_word_the_user_searched_is_never_a_negative() -> None:
    query = expand_with_rules("iphone charger")
    assert keeps(query, "Original iPhone charger 20W")


def test_empty_query_phrases_do_not_hide_results() -> None:
    query = ExpandedQuery(original="!!", normalized="")
    assert keeps(query, "anything")


def test_unrelated_prefix_collisions_do_not_match() -> None:
    query = ExpandedQuery(original="bike", normalized="bike")
    assert keeps(query, "Bikes for kids")
    assert not keeps(query, "Bicycle")  # needs a variant, not a fuzzy match
    assert not keeps(query, "Bikini")
