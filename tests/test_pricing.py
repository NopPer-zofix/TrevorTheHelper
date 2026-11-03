from decimal import Decimal

import pytest

from aggregator.domain.pricing import extract_price, parse_price

D = Decimal


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("€250", D("250")),
        ("€1,200", D("1200")),
        ("1 200 €", D("1200")),
        ("€1.200", D("1200")),
        ("1.200,50", D("1200.50")),
        ("1,200.50", D("1200.50")),
        ("€99.50", D("99.50")),
        ("€12,50", D("12.50")),
        ("1,200,000", D("1200000")),
        ("€0", None),
        ("Negotiable", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_price(text: str | None, expected: Decimal | None) -> None:
    assert parse_price(text) == expected


@pytest.mark.parametrize(
    ("text", "amount", "currency"),
    [
        ("iPhone 13 128gb, 250€", D("250"), "EUR"),
        ("Продам велосипед. Цена: 1 200 евро", D("1200"), "EUR"),
        ("Велосипед горный 26, 180 eur, Лимассол", D("180"), "EUR"),
        ("Price: 99,50", D("99.50"), "EUR"),
        ("цена 300", D("300"), "EUR"),
        ("MacBook $300 obo", D("300"), "USD"),
        ("£45 collection only", D("45"), "GBP"),
        ("Диван 15000 руб", D("15000"), "RUB"),
        ("было 300, сейчас 250 eur", D("250"), "EUR"),
        ("was 300 now 250€", D("250"), "EUR"),
        ("PS5 + 2 pads 350 euro", D("350"), "EUR"),
        ("Table 120€ chairs 40€", D("120"), "EUR"),
    ],
)
def test_extract_price(text: str, amount: Decimal, currency: str) -> None:
    found = extract_price(text)
    assert found is not None
    assert (found.amount, found.currency) == (amount, currency)


@pytest.mark.parametrize(
    "text",
    [
        "iPhone 13 pro 128gb like new",
        "Отдам даром диван",
        "neuroscience textbook",
        "Call 99 123456 for details",
        "Sofa 1 200€",  # ambiguous: 200 or 1 200 - refuse to guess
        "iPhone 13 250€",  # ambiguous: 250 or 13 250
    ],
)
def test_extract_price_finds_nothing(text: str) -> None:
    assert extract_price(text) is None
