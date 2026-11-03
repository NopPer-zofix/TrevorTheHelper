"""Price parsing shared by all sources: single amounts ("€1,200") and free-text extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

DEFAULT_CURRENCY = "EUR"  # Cyprus: a bare "price: 250" is assumed to be euros


def parse_price(text: str | None) -> Decimal | None:
    """Parse "€250", "€1,200", "1 200 €", "€1.200", "1.200,50". No digits -> None; zero -> None."""
    if not text:
        return None
    cleaned = re.sub(r"[^\d.,]", "", text)
    if not any(ch.isdigit() for ch in cleaned):
        return None
    if "." in cleaned and "," in cleaned:
        # Both present: the last one is the decimal mark, the other is a thousands separator.
        decimal_mark = "." if cleaned.rfind(".") > cleaned.rfind(",") else ","
        thousands = "," if decimal_mark == "." else "."
        cleaned = cleaned.replace(thousands, "").replace(decimal_mark, ".")
    elif re.fullmatch(r"\d{1,3}([.,]\d{3})+", cleaned):
        # "1.200" / "1,200" / "1,200,000": exactly three digits per group = thousands separators.
        cleaned = re.sub(r"[.,]", "", cleaned)
    else:
        cleaned = cleaned.replace(",", ".")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    return value if value > 0 else None


@dataclass(frozen=True)
class ExtractedPrice:
    amount: Decimal
    currency: str


_NUMBER = r"\d{1,3}(?:[  .,]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?"

# Currency word/symbol -> ISO code. Longest alternatives first matter for the regex below.
_CURRENCIES: dict[str, str] = {
    "€": "EUR",
    "eur": "EUR",
    "euro": "EUR",
    "euros": "EUR",
    "евро": "EUR",
    "$": "USD",
    "usd": "USD",
    "доллар": "USD",
    "долларов": "USD",
    "долл": "USD",
    "£": "GBP",
    "gbp": "GBP",
    "pounds": "GBP",
    "фунтов": "GBP",
    "₽": "RUB",
    "rub": "RUB",
    "руб": "RUB",
    "рублей": "RUB",
    "₴": "UAH",
    "uah": "UAH",
    "грн": "UAH",
}
_CUR = "|".join(re.escape(k) for k in sorted(_CURRENCIES, key=len, reverse=True))

# `(?<![\w])` / `(?![\w])` keep "eur" from matching inside words ("neuroscience", "euros1").
_AFTER = re.compile(rf"(?P<num>{_NUMBER})\s*(?P<cur>{_CUR})\.?(?![^\W\d_])", re.I)
_BEFORE = re.compile(rf"(?<![^\W\d_])(?P<cur>{_CUR})\s*(?P<num>{_NUMBER})", re.I)
_LABELLED = re.compile(
    rf"(?<![^\W\d_])(?:price|cost|цена|стоимость|ціна)\s*[:\-–—]?\s*(?P<num>{_NUMBER})",
    re.I,
)
# "was 300", "было 300": an old price, not the current one.
_OLD_PRICE_CONTEXT = re.compile(r"(?:was|old price|instead of|было|вместо|старая цена)\W*$", re.I)


def _is_ambiguous_space_grouping(number: str, before: str) -> bool:
    """A space-grouped number glued to a preceding word ("Sofa 1 200€") can't be trusted."""
    has_space_group = re.search(r"\d[  ]\d", number) is not None
    return has_space_group and re.search(r"[^\W_] $", before) is not None


def extract_price(text: str) -> ExtractedPrice | None:
    """Find the asking price in free text. The first plausible amount wins.

    Recognised: "250€", "€250", "250 eur", "250 евро", "$300", "цена 250" (assumed EUR).
    Skipped: amounts introduced as an old price ("было 300"), and space-grouped numbers glued to
    a word ("Sofa 1 200€", ambiguous with a model number). Known limitation: a post that
    lists several items with several prices yields only the first price.
    """
    candidates: list[tuple[int, ExtractedPrice]] = []
    for pattern in (_AFTER, _BEFORE, _LABELLED):
        for match in pattern.finditer(text):
            before = text[: match.start("num")]
            if _OLD_PRICE_CONTEXT.search(text[: match.start()]):
                continue
            if _is_ambiguous_space_grouping(match.group("num"), before):
                continue  # "iPhone 13 250€": 250 or 13 250? Better no price than a wrong one.
            amount = parse_price(match.group("num"))
            if amount is None:
                continue
            raw_currency = match.groupdict().get("cur")
            currency = _CURRENCIES[raw_currency.lower()] if raw_currency else DEFAULT_CURRENCY
            candidates.append((match.start(), ExtractedPrice(amount, currency)))
    if not candidates:
        return None
    return min(candidates, key=lambda c: c[0])[1]
