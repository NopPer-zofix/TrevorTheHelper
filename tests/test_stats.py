from datetime import UTC, datetime, timedelta
from decimal import Decimal

from aggregator.analytics.stats import compute_stats, find_best_deals, remove_outliers
from aggregator.domain.currency import CurrencyConverter
from aggregator.domain.models import Listing

D = Decimal
NOW = datetime(2026, 11, 1, tzinfo=UTC)


def make_listing(i: int, price: str | None, currency: str | None = "EUR") -> Listing:
    return Listing(
        source="bazaraki",
        external_id=str(i),
        url=f"https://example.test/{i}",
        title=f"item {i}",
        price_amount=D(price) if price is not None else None,
        currency=currency,
        posted_at=NOW - timedelta(days=i),
    )


def test_remove_outliers_drops_extreme_values() -> None:
    prices = [D(p) for p in (100, 110, 105, 95, 102, 108, 5000)]
    assert D(5000) not in remove_outliers(prices)
    assert len(remove_outliers(prices)) == 6


def test_remove_outliers_skips_tiny_samples() -> None:
    prices = [D(1), D(2), D(1000)]
    assert remove_outliers(prices) == prices


def test_compute_stats_basic() -> None:
    stats = compute_stats([D(100), D(200), D(300), None])
    assert stats.priced_count == 3
    assert stats.sample_size == 3
    assert stats.average == D("200")
    assert stats.median == D("200")
    assert (stats.minimum, stats.maximum) == (D(100), D(300))
    assert stats.reliable


def test_compute_stats_excludes_outliers_from_all_figures() -> None:
    stats = compute_stats([D(p) for p in (100, 110, 105, 95, 102, 108, 5000)])
    assert stats.outliers_removed == 1
    assert stats.sample_size == 6
    assert stats.maximum == D(110)
    assert stats.average is not None
    assert stats.average < 120


def test_few_priced_listings_are_unreliable() -> None:
    stats = compute_stats([D(100), D(120), None, None])
    assert stats.sample_size == 2
    assert not stats.reliable
    assert stats.median == D("110")


def test_no_prices_gives_empty_stats() -> None:
    stats = compute_stats([None, None])
    assert stats.priced_count == 0
    assert stats.average is None
    assert not stats.reliable


def test_best_deals_need_five_priced_listings() -> None:
    listings = [make_listing(i, p) for i, p in enumerate(["100", "100", "100", "50"])]
    assert find_best_deals(listings) == []


def test_best_deals_threshold_and_ordering() -> None:
    prices = ["500", "520", "480", "510", "300", "400", "250"]
    listings = [make_listing(i, p) for i, p in enumerate(prices)]
    deals = find_best_deals(listings, ratio=0.75)
    # median of the sample is 480 -> threshold 360: only 300 and 250 qualify
    assert [d.listing.price_amount for d in deals] == [D(250), D(300)]
    assert deals[0].discount_pct == 48
    assert deals[1].discount_pct == 38


def test_best_deals_ignore_bait_prices() -> None:
    prices = ["500", "520", "480", "510", "490", "505", "1"]
    listings = [make_listing(i, p) for i, p in enumerate(prices)]
    assert find_best_deals(listings) == []


def test_best_deals_capped_at_three_and_skip_unpriced() -> None:
    prices = ["400"] * 5 + ["100", "110", "120", "130", None]
    listings = [make_listing(i, p) for i, p in enumerate(prices)]
    deals = find_best_deals(listings)
    assert len(deals) == 3
    assert all(d.listing.price_amount is not None for d in deals)


def test_best_deals_use_eur_normalized_prices() -> None:
    listings = [make_listing(i, p) for i, p in enumerate(["380", "400", "420", "390", "410"])]
    listings.append(make_listing(9, "300", "USD"))
    # 300 USD = 276 EUR: a statistical outlier of a tight cluster, yet a real deal (31% off)
    deals = find_best_deals(listings)
    assert [d.listing.external_id for d in deals] == ["9"]
    assert deals[0].discount_pct == 31


def test_price_eur_conversion() -> None:
    assert make_listing(1, "100", "EUR").price_eur == D("100.00")
    assert make_listing(1, "100", "USD").price_eur == D("92.00")
    assert make_listing(1, "100", "XXX").price_eur is None
    assert make_listing(1, None).price_eur is None
    assert make_listing(1, "100", None).price_eur is None


def test_converter_accepts_custom_rates() -> None:
    converter = CurrencyConverter({"eur": D(1), "xyz": D("2")})
    assert converter.to_eur(D(10), "XYZ") == D("20.00")
