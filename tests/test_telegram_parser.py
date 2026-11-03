from decimal import Decimal

import pytest

from aggregator.domain.cities import City
from aggregator.sources.telegram.parser import MAX_TITLE_LENGTH, parse_message


class TestTitleAndDescription:
    def test_first_meaningful_line_is_title(self) -> None:
        parsed = parse_message("Велосипед Trek FX 2\nПочти новый, 250€\nЛимассол")
        assert parsed.title == "Велосипед Trek FX 2"
        assert parsed.description == "Почти новый, 250€\nЛимассол"

    def test_hashtags_and_emoji_are_stripped(self) -> None:
        parsed = parse_message("🔥🔥 #продам #limassol 🚲 Trek FX 2 ✨\nGood condition")
        assert parsed.title == "Trek FX 2"

    def test_leading_decoration_only_lines_are_skipped(self) -> None:
        parsed = parse_message("#sale #limassol\n\n🔥🔥🔥\nIKEA desk 80€")
        assert parsed.title == "IKEA desk 80€"
        assert parsed.description is None

    def test_currency_symbols_survive_cleaning(self) -> None:
        assert parse_message("Sofa €200").title == "Sofa €200"

    def test_long_title_is_truncated_and_full_text_kept_in_description(self) -> None:
        line = " ".join(["word"] * 60)
        parsed = parse_message(f"{line}\nsecond line")
        assert len(parsed.title) <= MAX_TITLE_LENGTH
        assert parsed.title.endswith("…")
        assert parsed.description is not None
        assert parsed.description.startswith(line)
        assert parsed.description.endswith("second line")

    @pytest.mark.parametrize("text", ["", "   \n\n", "#tag #other", "🔥🔥🔥"])
    def test_empty_or_decoration_only_message(self, text: str) -> None:
        parsed = parse_message(text)
        assert parsed.title == ""
        assert parsed.description is None
        assert parsed.price is None
        assert not parsed.is_sold
        assert not parsed.is_wanted


class TestSold:
    @pytest.mark.parametrize(
        "text",
        [
            "ПРОДАНО iPhone 13 300€",
            "iPhone 13 300€\nпродан",
            "Диван 100€ (продана)",
            "Стол продано",
            "Bike 200 eur - SOLD",
            "Sold! Trek bike",
            "Куртка, неактуально",
            "Куртка, не актуально",
        ],
    )
    def test_sold_markers(self, text: str) -> None:
        assert parse_message(text).is_sold

    @pytest.mark.parametrize(
        "text",
        [
            "Продаю велосипед 200€",
            "Продается диван, 150 евро",
            "Продам iPhone 13",
            "Актуально! Велосипед 200€",
            "Personalised gifts for sale",
        ],
    )
    def test_sale_offers_are_not_sold(self, text: str) -> None:
        assert not parse_message(text).is_sold


class TestWanted:
    @pytest.mark.parametrize(
        "text",
        [
            "Куплю велосипед до 200€",
            "Ищу диван в Лимассоле",
            "WTB iPhone 13",
            "Looking for a used bike",
            "I want to buy a sofa",
            "Wanted: desk",
        ],
    )
    def test_wanted_markers(self, text: str) -> None:
        assert parse_message(text).is_wanted

    @pytest.mark.parametrize(
        "text",
        [
            "Продаю велосипед 200€",
            "Продается диван",
            "Selling iPhone 13, 300€",
        ],
    )
    def test_sale_offers_are_not_wanted(self, text: str) -> None:
        assert not parse_message(text).is_wanted

    def test_marker_far_from_the_start_is_ignored(self) -> None:
        text = (
            "Продаю велосипед в отличном состоянии. " + "Очень удобный. " * 10 + "Ищу хорошие руки."
        )
        assert not parse_message(text).is_wanted

    def test_word_boundaries(self) -> None:
        assert not parse_message("Unwanted gift, never used").is_wanted
        assert not parse_message("Дом ищущий хозяина").is_wanted


class TestFields:
    def test_price_and_city_are_extracted(self) -> None:
        parsed = parse_message("Диван угловой\nЦена 350€, Лимассол, самовывоз")
        assert parsed.price is not None
        assert parsed.price.amount == Decimal("350")
        assert parsed.price.currency == "EUR"
        assert parsed.city is City.LIMASSOL

    def test_english_city(self) -> None:
        assert parse_message("Desk 80 eur, Paphos").city is City.PAPHOS

    def test_unknown_city_and_no_price(self) -> None:
        parsed = parse_message("Free sofa, take it away")
        assert parsed.city is City.UNKNOWN
        assert parsed.price is None
