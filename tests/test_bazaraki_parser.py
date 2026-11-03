from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from aggregator.domain.cities import City
from aggregator.sources.base import SourceError
from aggregator.sources.bazaraki.parser import parse_price, parse_published, parse_search_page

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parses_cards_and_skips_non_listings() -> None:
    page = parse_search_page(load("bazaraki_search.html"), now=NOW)
    assert [item.external_id for item in page.listings] == [
        "1000001",
        "1000002",
        "1000003",
        "1000004",
    ]  # the promo slot without id/url is ignored


def test_card_fields() -> None:
    first = parse_search_page(load("bazaraki_search.html"), now=NOW).listings[0]
    assert first.source == "bazaraki"
    assert first.title == "Iphone 13"
    assert first.url == "https://www.bazaraki.com/adv/1000001_iphone-13/"
    assert first.price_amount == Decimal("250")
    assert first.currency == "EUR"
    assert first.price_eur == Decimal("250.00")
    assert first.city is City.LIMASSOL
    assert first.posted_at == NOW - timedelta(weeks=1)


def test_thousands_separator_negotiable_and_unknown_location() -> None:
    by_id = {
        item.external_id: item
        for item in parse_search_page(load("bazaraki_search.html"), now=NOW).listings
    }
    assert by_id["1000002"].price_amount == Decimal("1200")
    assert by_id["1000002"].city is City.NICOSIA
    assert by_id["1000002"].posted_at == NOW - timedelta(days=1)

    assert by_id["1000003"].price_amount is None  # "Negotiable" -> null price
    assert by_id["1000003"].currency is None
    assert by_id["1000003"].posted_at == NOW - timedelta(minutes=12)

    assert by_id["1000004"].city is City.UNKNOWN  # location "Cyprus" names no city


def test_searched_city_fills_in_unrecognised_locations() -> None:
    page = parse_search_page(load("bazaraki_search.html"), now=NOW, searched_city=City.LIMASSOL)
    by_id = {item.external_id: item for item in page.listings}
    assert by_id["1000004"].city is City.LIMASSOL  # district-scoped request
    assert by_id["1000002"].city is City.NICOSIA  # a detected city is never overridden


def test_pagination_detection() -> None:
    assert parse_search_page(load("bazaraki_search.html"), now=NOW, page=1).has_next_page
    last = parse_search_page(load("bazaraki_last_page.html"), now=NOW, page=2)
    assert not last.has_next_page
    assert [item.external_id for item in last.listings] == ["1000005"]
    assert last.listings[0].city is City.PAPHOS


def test_page_without_advert_data_is_an_error_not_an_empty_result() -> None:
    with pytest.raises(SourceError):
        parse_search_page("<html><body>captcha?</body></html>", now=NOW)


def test_empty_result_set_is_fine() -> None:
    html = '<script>self.__next_f.push([1,"{\\"adverts\\":[]}"])</script>'
    page = parse_search_page(html, now=NOW)
    assert page.listings == []


def test_description_is_kept_when_present() -> None:
    by_id = {
        i.external_id: i for i in parse_search_page(load("bazaraki_search.html"), now=NOW).listings
    }
    assert by_id["1000002"].description == "Battery 91%, with box"
    assert by_id["1000001"].description is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("€250", Decimal("250")),
        ("€1,200", Decimal("1200")),
        ("1 200 €", Decimal("1200")),
        ("€1.200", Decimal("1200")),
        ("€99.50", Decimal("99.50")),
        ("€12,50", Decimal("12.50")),
        ("€0", None),
        ("Negotiable", None),
        ("Free", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_price(text: str | None, expected: Decimal | None) -> None:
    assert parse_price(text) == expected


@pytest.mark.parametrize(
    ("text", "delta"),
    [
        ("Today", timedelta(0)),
        ("Yesterday", timedelta(days=1)),
        ("12 minutes ago", timedelta(minutes=12)),
        ("5 hours ago", timedelta(hours=5)),
        ("3 days ago", timedelta(days=3)),
        ("2 weeks ago", timedelta(weeks=2)),
        ("1 month ago", timedelta(days=30)),
        ("2 months ago", timedelta(days=60)),
        ("something odd", timedelta(0)),
        (None, timedelta(0)),
    ],
)
def test_parse_published(text: str | None, delta: timedelta) -> None:
    assert parse_published(text, NOW) == NOW - delta
