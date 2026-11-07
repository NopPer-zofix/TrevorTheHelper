"""Price cases: normal / unusually low / unusually high, and how the result view uses them."""

from __future__ import annotations

from decimal import Decimal

import pytest

from aggregator.analytics.price_cases import PriceCase, PriceCuts, find_price_cuts
from aggregator.bot.formatting import format_results
from aggregator.bot.i18n import Texts
from aggregator.domain.cities import City
from aggregator.domain.models import ExpandedQuery, Filters
from aggregator.search.filters import build_view
from aggregator.search.models import SearchOutcome, SourceStatus
from factories import make_listing


def dec(*values: float) -> list[Decimal]:
    return [Decimal(str(v)) for v in values]


# Phones around EUR 300 with the junk seen on the real site: a case, a part, a "for parts" phone.
PHONES = [270, 280, 290, 300, 310, 320, 330, 350, 360, 380, 299, 305, 315, 285, 295]


def cases_of(prices: list[float]) -> dict[float, PriceCase]:
    cuts = find_price_cuts(dec(*prices))
    return {p: cuts.case_of(Decimal(str(p))) for p in prices}


# --- the algorithm -------------------------------------------------------------------------


def test_a_few_tiny_prices_among_a_normal_group_are_low() -> None:
    cases = cases_of([*PHONES, 4, 5, 12])
    assert cases[4] is cases[5] is cases[12] is PriceCase.LOW
    assert all(cases[p] is PriceCase.NORMAL for p in PHONES)


def test_a_typo_price_is_high() -> None:
    cases = cases_of([*PHONES, 30000])
    assert cases[30000] is PriceCase.HIGH
    assert cases[300] is PriceCase.NORMAL


def test_a_genuine_discount_is_not_called_unusual() -> None:
    cases = cases_of([*PHONES, 230, 450])  # about -25% / +50% of the centre
    assert cases[230] is PriceCase.NORMAL and cases[450] is PriceCase.NORMAL


def test_wide_distributions_are_judged_on_a_multiplicative_scale() -> None:
    laptops = [250, 400, 550, 700, 850, 1000, 1200, 1500, 1800, 2200]  # EUR 250..2200 is normal
    cases = cases_of([*laptops, 9])  # a charger
    assert cases[9] is PriceCase.LOW
    assert cases[250] is PriceCase.NORMAL and cases[2200] is PriceCase.NORMAL


def test_a_tight_cluster_does_not_turn_small_differences_into_outliers() -> None:
    cases = cases_of([300, 300, 301, 299, 300, 302, 298, 300, 310])  # spread would be ~0
    assert set(cases.values()) == {PriceCase.NORMAL}


def test_too_few_prices_flag_nothing() -> None:
    cuts = find_price_cuts(dec(300, 310, 5, 290, 305))  # only 5 priced
    assert cuts == PriceCuts()
    assert cuts.case_of(Decimal(5)) is PriceCase.NORMAL


def test_a_contaminated_set_is_cleaned_in_the_second_pass() -> None:
    # 40% junk (10 of 25): the first pass sees an inflated spread, the second sees the real group.
    junk = [2.0, 2.0, 2.0, 15.0, 20.0, 35.0, 40.0, 55.0, 72.0, 80.0]
    cases = cases_of([*PHONES, *junk])
    assert sum(1 for p in set(junk) if cases[p] is PriceCase.LOW) == len(set(junk))
    assert all(cases[p] is PriceCase.NORMAL for p in PHONES)


def test_more_junk_than_real_items_is_reported_as_mixed_not_guessed() -> None:
    # 20 junk vs 15 phones: no group reaches 60%, so the honest answer is "can't tell".
    junk = [2.0] * 10 + [15.0, 20.0, 35.0, 40.0, 55.0, 60.0, 72.0, 80.0, 25.0, 30.0]
    cuts = find_price_cuts(dec(*PHONES, *junk))
    assert cuts.mixed is True
    assert cuts.case_of(Decimal(2)) is PriceCase.NORMAL  # nothing is hidden when we can't tell


def test_a_genuinely_mixed_set_flags_nothing() -> None:
    # Two equally big groups far apart: no dominant cluster, so hiding either would be a guess.
    mixed = [20, 22, 25, 21, 23, 24, 500, 520, 480, 510, 495, 505]
    cuts = find_price_cuts(dec(*mixed))
    assert cuts.mixed is True
    assert all(cuts.case_of(Decimal(p)) is PriceCase.NORMAL for p in mixed)


def test_zero_price_is_low_when_cuts_exist() -> None:
    cuts = find_price_cuts(dec(*PHONES))
    assert cuts.case_of(Decimal(0)) is PriceCase.LOW
    assert cuts.case_of(None) is PriceCase.NORMAL


# --- the view ------------------------------------------------------------------------------


def listings_with(prices: list[float], source: str = "bazaraki"):
    return [
        make_listing(f"Phone {i}", price=p, source=source, external_id=f"{source}-{i}")
        for i, p in enumerate(prices)
    ]


JUNK_PRICES = [4, 5, 12]


def test_unusual_listings_are_hidden_and_excluded_from_stats_by_default() -> None:
    listings = listings_with([*PHONES, *JUNK_PRICES])
    view = build_view(listings, Filters())
    assert len(view.listings) == len(PHONES)
    assert view.unusual.low_count == 3 and view.unusual.high_count == 0
    assert view.stats.minimum is not None and view.stats.minimum >= 270
    assert len(view.unusual_keys) == 3


def test_showing_unusual_keeps_them_in_the_list_but_not_in_the_stats() -> None:
    listings = listings_with([*PHONES, *JUNK_PRICES])
    view = build_view(listings, Filters(show_unusual_prices=True))
    assert len(view.listings) == len(PHONES) + 3
    assert view.stats.minimum is not None and view.stats.minimum >= 270  # still not counted
    assert view.best_deals == [] or all(d.listing.price_eur >= 200 for d in view.best_deals)
    assert len(view.unusual_keys) == 3


def test_user_price_filter_does_not_move_the_boundaries() -> None:
    listings = listings_with([*PHONES, *JUNK_PRICES])
    narrow = build_view(listings, Filters(min_price=Decimal(290)))
    assert narrow.unusual.low_count == 0  # the junk fails the user's own min price anyway
    assert all(li.price_eur >= 290 for li in narrow.listings)
    assert narrow.unusual.low_below == build_view(listings, Filters()).unusual.low_below


def test_unusual_counts_follow_the_source_filter() -> None:
    listings = [
        *listings_with(PHONES, "bazaraki"),
        *listings_with(JUNK_PRICES, "telegram"),
    ]
    only_bazaraki = build_view(listings, Filters(source="bazaraki"))
    assert only_bazaraki.unusual.count == 0
    only_telegram = build_view(listings, Filters(source="telegram"))
    assert only_telegram.unusual.low_count == 3 and only_telegram.listings == []


def test_unpriced_listings_are_never_unusual() -> None:
    listings = [*listings_with(PHONES), make_listing("No price", price=None, external_id="np")]
    view = build_view(listings, Filters())
    assert len(view.listings) == len(PHONES) + 1
    assert view.unusual.count == 0


# --- the message ---------------------------------------------------------------------------


def outcome_of(listings) -> SearchOutcome:
    return SearchOutcome(
        query=ExpandedQuery(original="iphone 13", normalized="iphone 13"),
        city=City.LIMASSOL,
        listings=listings,
        statuses=[SourceStatus(name="bazaraki", ok=True, count=len(listings))],
    )


def test_message_tells_how_many_were_hidden_and_why() -> None:
    listings = listings_with([*PHONES, *JUNK_PRICES])
    text = format_results(Texts("en"), outcome_of(listings), build_view(listings, Filters()), 0)
    assert "3 listing(s) with unusual prices hidden" in text
    assert "under €" in text
    assert "⚠️ €" not in text  # hidden ones have no marker


def test_shown_unusual_listings_are_marked_and_explained() -> None:
    listings = listings_with([*PHONES, *JUNK_PRICES])
    filters = Filters(show_unusual_prices=True, sort="cheapest")
    view = build_view(listings, filters)
    text = format_results(Texts("en"), outcome_of(listings), view, 0, filters)
    assert "⚠️ €4" in text and "not counted in the statistics" in text
    assert "hidden" not in text.split("Listings")[0].lower().replace("filters", "")


def test_mixed_sets_get_a_warning_instead_of_hiding() -> None:
    mixed = [20, 22, 25, 21, 23, 24, 500, 520, 480, 510, 495, 505]
    listings = listings_with(mixed)
    view = build_view(listings, Filters())
    assert len(view.listings) == len(mixed)  # nothing hidden
    text = format_results(Texts("en"), outcome_of(listings), view, 0)
    assert "vary a lot" in text


def test_russian_note_is_translated() -> None:
    listings = listings_with([*PHONES, *JUNK_PRICES])
    text = format_results(Texts("ru"), outcome_of(listings), build_view(listings, Filters()), 0)
    assert "Скрыто объявлений с необычной ценой: 3" in text and "ниже €" in text


@pytest.mark.parametrize("lang", ["en", "ru"])
def test_every_new_text_exists_in_both_languages(lang: str) -> None:
    t = Texts(lang)
    for key in ("unusual_hidden", "unusual_mixed", "unusual_shown", "filter_unusual"):
        assert t(key)
