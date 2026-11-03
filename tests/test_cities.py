import pytest

from aggregator.domain.cities import City, city_matches, detect_city


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("iPhone 13 for sale in Limassol", City.LIMASSOL),
        ("Продам велосипед, Лимассол, самовывоз", City.LIMASSOL),
        ("Отдам в Лимассоле диван", City.LIMASSOL),
        ("Location: Limasol, Germasogeia", City.LIMASSOL),
        ("Lemesos area", City.LIMASSOL),
        ("Nicosia, Strovolos", City.NICOSIA),
        ("Продаю в Никосии", City.NICOSIA),
        ("Lefkosia pickup", City.NICOSIA),
        ("Larnaka centre", City.LARNACA),
        ("Ларнака, район Ливадия", City.LARNACA),
        ("Пафос, Като Пафос", City.PAPHOS),
        ("Pafos old town", City.PAPHOS),
        ("Фамагуста, Айя-Напа", City.FAMAGUSTA),
        ("Protaras beach house", City.FAMAGUSTA),
        ("Ёлка новая, Лимассол", City.LIMASSOL),
        ("Just a nice chair", City.UNKNOWN),
        ("", City.UNKNOWN),
    ],
)
def test_detect_city(text: str, expected: City) -> None:
    assert detect_city(text) is expected


def test_first_mentioned_city_wins() -> None:
    assert detect_city("In Limassol, can deliver to Paphos") is City.LIMASSOL
    assert detect_city("Доставка в Пафос, сам в Никосии") is City.PAPHOS


def test_city_inside_a_longer_word_is_not_matched() -> None:
    assert detect_city("unpafosed") is City.UNKNOWN


def test_all_cyprus_includes_unknown_but_specific_city_does_not() -> None:
    assert city_matches(City.UNKNOWN, City.ALL_CYPRUS)
    assert city_matches(City.UNKNOWN, None)
    assert city_matches(City.PAPHOS, City.ALL_CYPRUS)
    assert not city_matches(City.UNKNOWN, City.LIMASSOL)
    assert not city_matches(City.PAPHOS, City.LIMASSOL)
    assert city_matches(City.LIMASSOL, City.LIMASSOL)
