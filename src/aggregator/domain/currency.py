"""EUR normalization. Rates are static and approximate; inject your own for anything finer."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

# Approximate EUR value of one unit. Cyprus listings are almost always EUR; the rest is a
# best-effort fallback for Telegram posts. Replace with a live-rate provider if it matters.
DEFAULT_RATES_TO_EUR: Mapping[str, Decimal] = {
    "EUR": Decimal("1"),
    "USD": Decimal("0.92"),
    "GBP": Decimal("1.17"),
    "RUB": Decimal("0.010"),
    "UAH": Decimal("0.023"),
}


class CurrencyConverter:
    def __init__(self, rates: Mapping[str, Decimal] = DEFAULT_RATES_TO_EUR) -> None:
        self._rates = {code.upper(): rate for code, rate in rates.items()}

    def to_eur(self, amount: Decimal | None, currency: str | None) -> Decimal | None:
        """Convert to EUR. Missing amount, missing currency or an unknown currency -> None."""
        if amount is None or currency is None:
            return None
        rate = self._rates.get(currency.upper())
        if rate is None:
            return None
        return (amount * rate).quantize(Decimal("0.01"))
