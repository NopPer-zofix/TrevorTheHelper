"""Category catalog, the ask-or-pick decision, and category-scoped Bazaraki searching."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import respx

from aggregator.cache import InMemoryTTLCache
from aggregator.domain.categories import (
    CATALOG,
    category_label,
    is_known_category,
    is_offered,
    normalize_path,
    short_label,
)
from aggregator.domain.cities import City
from aggregator.domain.models import ExpandedQuery, Filters, Listing
from aggregator.search.category_choice import (
    RENT,
    SALE,
    Ask,
    CategoryOption,
    Resolved,
    decide,
    intent_of,
)
from aggregator.search.orchestrator import SearchOrchestrator
from aggregator.services.search_service import SearchService
from aggregator.services.users import UserProfile
from aggregator.sources.base import CategoryExplorer, SourceError
from aggregator.sources.bazaraki.client import BazarakiClient
from aggregator.sources.bazaraki.parser import advert_category, parse_search_page
from aggregator.sources.bazaraki.selectors import search_path
from aggregator.sources.bazaraki.source import BazarakiSource
from factories import make_listing
from test_orchestrator import FakeSource

NOW = datetime(2026, 11, 7, tzinfo=UTC)

# --- the catalog ---------------------------------------------------------------------------


def test_catalog_has_the_two_level_tree() -> None:
    tops = [c for c in CATALOG.values() if c.depth == 1]
    assert len(tops) == 16
    assert all("/" in p or p in {c.path for c in tops} for p in CATALOG)
    for category in CATALOG.values():
        if category.depth == 2:
            assert category.path.split("/")[0] in CATALOG  # every child has a known parent


def test_every_top_level_category_has_a_russian_name() -> None:
    assert all(c.ru for c in CATALOG.values() if c.depth == 1)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("telephones/mobile-phones/iphone", "telephones/mobile-phones"),  # deeper levels are cut
        ("telephones/mobile-phones", "telephones/mobile-phones"),
        ("telephones/no-such-child", "telephones"),  # unknown child: keep the known parent
        ("/telephones/", "telephones"),
        ("no-such-category", None),
        ("", None),
        (None, None),
    ],
)
def test_normalize_path(raw: str | None, expected: str | None) -> None:
    assert normalize_path(raw) == expected


def test_labels_in_both_languages_with_english_fallback() -> None:
    path = "real-estate-to-rent/apartments-flats"
    assert category_label(path, "en") == "Real Estate to rent › Apartments, flats"
    assert category_label(path, "ru") == "Недвижимость: аренда › Квартиры"
    assert short_label(path, "ru") == "Квартиры"
    assert category_label("jobs-and-services/teachers", "ru").endswith("Education")  # no RU name
    assert (
        category_label(None) == ""
        and category_label("telephones") == "Mobile phones, communication"
    )


def test_adult_categories_are_never_offered() -> None:
    assert is_known_category("beauty-and-health/massage")
    assert not is_offered("beauty-and-health/massage")
    assert not is_offered("beauty-and-health/adult-products-18")
    assert is_offered("beauty-and-health/make-up")
    assert not is_offered("made/up")


# --- the decision --------------------------------------------------------------------------

PHONES = "telephones/mobile-phones"


def test_a_dominant_category_is_picked_without_asking() -> None:
    counts = {PHONES: 56, "telephones/accessories": 4}  # 93% phones
    assert decide(counts) == Resolved(PHONES)


def test_an_even_split_asks_with_counts_most_frequent_first() -> None:
    counts = {PHONES: 52, "telephones/phone-parts": 22, "telephones/accessories": 19}
    decision = decide(counts)
    assert decision == Ask(
        prefix="telephones",
        options=(
            CategoryOption(PHONES, 52),
            CategoryOption("telephones/phone-parts", 22),
            CategoryOption("telephones/accessories", 19),
        ),
    )


def test_rare_categories_are_not_offered() -> None:
    counts = {PHONES: 50, "telephones/accessories": 40, "telephones/smart-watches": 2}
    decision = decide(counts)
    assert isinstance(decision, Ask)
    assert [o.path for o in decision.options] == [PHONES, "telephones/accessories"]


PROPERTY = {
    "real-estate-for-sale/apartments-flats": 30,
    "real-estate-for-sale/houses": 10,
    "real-estate-to-rent/apartments-flats": 12,
    "real-estate-to-rent/houses": 3,
}


def test_rent_versus_sale_is_asked_first_even_when_sale_dominates() -> None:
    decision = decide({**PROPERTY, "real-estate-for-sale/apartments-flats": 300})
    assert isinstance(decision, Ask) and decision.prefix is None
    assert [o.path for o in decision.options] == [SALE, RENT]


def test_then_flat_versus_house_is_asked() -> None:
    first = decide(PROPERTY)
    assert isinstance(first, Ask)
    second = decide(PROPERTY, RENT)
    assert second == Ask(
        prefix=RENT,
        options=(
            CategoryOption("real-estate-to-rent/apartments-flats", 12),
            CategoryOption("real-estate-to-rent/houses", 3),
        ),
    )
    assert decide(PROPERTY, "real-estate-to-rent/apartments-flats") == Resolved(
        "real-estate-to-rent/apartments-flats"
    )


def test_a_rent_word_in_the_query_skips_the_first_question() -> None:
    decision = decide(PROPERTY, None, "rent")
    assert isinstance(decision, Ask) and decision.prefix == RENT  # straight to flat / house


def test_a_sale_word_selects_sale() -> None:
    counts = {
        "real-estate-for-sale/apartments-flats": 40,
        "real-estate-to-rent/apartments-flats": 20,
    }
    assert decide(counts, None, "sale") == Resolved("real-estate-for-sale/apartments-flats")


def test_an_intent_for_a_category_not_in_the_results_is_ignored() -> None:
    assert decide({PHONES: 40}, None, "rent") == Resolved(PHONES)


def test_a_single_stray_ad_of_the_other_kind_does_not_trigger_the_question() -> None:
    counts = {
        "real-estate-for-sale/apartments-flats": 98,
        "real-estate-to-rent/apartments-flats": 1,
    }
    assert decide(counts) == Resolved("real-estate-for-sale/apartments-flats")


def test_a_handful_of_the_other_kind_does_trigger_it() -> None:
    counts = {
        "real-estate-for-sale/apartments-flats": 98,
        "real-estate-to-rent/apartments-flats": 2,
    }
    decision = decide(counts)
    assert isinstance(decision, Ask)
    assert [o.path for o in decision.options] == [SALE, RENT]


def test_too_small_a_sample_decides_nothing() -> None:
    assert decide({PHONES: 3}) == Resolved(None)
    assert decide({}) == Resolved(None)


def test_top_level_only_results_resolve_to_the_top_level() -> None:
    assert decide({"free-stuff": 20}) == Resolved("free-stuff")


def test_adult_categories_never_appear_as_options() -> None:
    counts = {"beauty-and-health/massage": 30, "beauty-and-health/make-up": 20, "animals/dogs": 20}
    decision = decide(counts)
    paths = {o.path for o in decision.options} if isinstance(decision, Ask) else set()
    assert "beauty-and-health/massage" not in paths


@pytest.mark.parametrize(
    ("text", "intent"),
    [
        ("3 bedroom apartment for rent", "rent"),
        ("квартира аренда лимассол", "rent"),
        ("2 bed flat to rent", "rent"),
        ("house for sale", "sale"),
        ("купить дом", "sale"),
        ("3 bedroom apartment", None),
        ("rent or sale", None),  # contradictory
        ("parent", None),  # whole words only
    ],
)
def test_intent_of(text: str, intent: str | None) -> None:
    assert intent_of(text) == intent


# --- parsing the category from Bazaraki adverts --------------------------------------------


def advert(
    ident: int,
    title: str,
    price: int,
    ancestors: list[str] | None,
    location: str = "Limassol — X",
    leaf: str = "leaf",
) -> dict[str, Any]:
    rubric: dict[str, Any] = {"slug": leaf}
    if ancestors is not None:
        rubric["ancestors"] = [{"slug": slug} for slug in ancestors]
    return {
        "id": ident,
        "title": title,
        "description": "",
        "price": f"€{price}",
        "price_without_currency": str(price),
        "currency": "EUR",
        "published": "1 day ago",
        "url": f"/adv/{ident}_x/",
        "location": location,
        "rubric": rubric,
    }


def page(adverts: list[dict[str, Any]]) -> str:
    stream = f'1a:["$","div",null,{{"count":{len(adverts)},"adverts":{json.dumps(adverts)}}}]'
    return (
        f"<html><body><script>self.__next_f.push([1,{json.dumps(stream)}])</script></body></html>"
    )


def test_the_rubric_itself_is_the_last_level_of_the_path() -> None:
    """Real shape seen on the live site: a flat ad has ancestors [real-estate-to-rent] only, and
    its own category (apartments-flats) is the rubric's slug."""
    flat_ad = advert(1, "x", 1, ["real-estate-to-rent"], leaf="apartments-flats")
    assert advert_category(flat_ad) == "real-estate-to-rent/apartments-flats"
    house_ad = advert(2, "x", 1, ["real-estate-for-sale"], leaf="houses")
    assert advert_category(house_ad) == "real-estate-for-sale/houses"
    # An iPhone ad: three ancestors, a model-level rubric; everything below level 2 is cut.
    phone_ad = advert(3, "x", 1, ["telephones", "mobile-phones", "iphone"], leaf="iphone-13")
    assert advert_category(phone_ad) == PHONES


def test_advert_category_is_reduced_to_the_catalog() -> None:
    assert advert_category(advert(1, "x", 1, ["telephones", "mobile-phones", "iphone"])) == PHONES
    assert advert_category(advert(1, "x", 1, ["telephones"])) == "telephones"
    assert advert_category(advert(1, "x", 1, ["something", "else"])) is None
    assert advert_category(advert(1, "x", 1, None)) is None  # no ancestors at all
    assert advert_category({"id": 1}) is None  # no rubric at all
    assert advert_category({"rubric": "oops"}) is None  # unexpected shape: never crash


def test_listings_carry_their_category() -> None:
    html = page(
        [
            advert(1, "Iphone 13", 300, ["telephones", "mobile-phones", "iphone"]),
            advert(2, "Iphone 13 case", 5, ["telephones", "accessories"]),
        ]
    )
    listings = parse_search_page(html, now=NOW).listings
    assert [li.category for li in listings] == [PHONES, "telephones/accessories"]


# --- category-scoped Bazaraki search -------------------------------------------------------


def test_search_paths() -> None:
    assert search_path(None) == "/search/"
    assert search_path("limassol") == "/search/lemesos-district-limassol/"
    assert search_path(None, PHONES) == "/telephones/mobile-phones/"
    assert search_path("limassol", PHONES) == "/telephones/mobile-phones/lemesos-district-limassol/"


class Sleeps:
    async def __call__(self, seconds: float) -> None:
        return None


def make_source() -> BazarakiSource:
    client = BazarakiClient(user_agent="T/0", min_interval_seconds=0, sleep=Sleeps())
    cache: InMemoryTTLCache[list[Listing]] = InMemoryTTLCache()
    return BazarakiSource(client, cache, now=lambda: NOW, max_pages=1, max_terms=1)


def query() -> ExpandedQuery:
    return ExpandedQuery(original="iphone 13", normalized="iphone 13")


@respx.mock
async def test_a_category_scopes_the_request_path() -> None:
    route = respx.get(
        "https://www.bazaraki.com/telephones/mobile-phones/lemesos-district-limassol/"
    ).mock(
        return_value=httpx.Response(
            200, text=page([advert(1, "Iphone 13", 300, ["telephones", "mobile-phones"])])
        )
    )
    found = await make_source().search(query(), City.LIMASSOL, Filters(category=PHONES))
    assert route.call_count == 1 and [li.external_id for li in found] == ["1"]


@respx.mock
async def test_an_unknown_category_is_never_put_in_a_url() -> None:
    route = respx.get("https://www.bazaraki.com/search/").mock(
        return_value=httpx.Response(200, text=page([advert(1, "Iphone 13", 300, ["telephones"])]))
    )
    await make_source().search(query(), City.ALL_CYPRUS, Filters(category="../admin/secret"))
    assert route.call_count == 1  # fell back to the plain search path


@respx.mock
async def test_results_are_cached_per_category() -> None:
    plain = respx.get("https://www.bazaraki.com/search/").mock(
        return_value=httpx.Response(200, text=page([advert(1, "Iphone 13", 300, ["telephones"])]))
    )
    scoped = respx.get("https://www.bazaraki.com/telephones/mobile-phones/").mock(
        return_value=httpx.Response(
            200, text=page([advert(2, "Iphone 13", 310, ["telephones", "mobile-phones"])])
        )
    )
    source = make_source()
    first = await source.search(query(), City.ALL_CYPRUS, Filters())
    second = await source.search(query(), City.ALL_CYPRUS, Filters(category=PHONES))
    again = await source.search(query(), City.ALL_CYPRUS, Filters(category=PHONES))
    assert [li.external_id for li in first] == ["1"]
    assert [li.external_id for li in second] == ["2"] == [li.external_id for li in again]
    assert plain.call_count == 1 and scoped.call_count == 1  # no mix-up, and the repeat is cached


@respx.mock
async def test_explore_counts_categories_with_one_cached_request() -> None:
    route = respx.get("https://www.bazaraki.com/search/lemesos-district-limassol/").mock(
        return_value=httpx.Response(
            200,
            text=page(
                [
                    advert(1, "a", 1, ["telephones", "mobile-phones", "iphone"]),
                    advert(2, "b", 1, ["telephones", "mobile-phones"]),
                    advert(3, "c", 1, ["telephones", "accessories"]),
                    advert(4, "d", 1, ["unknown", "thing"]),  # not in the catalog: not counted
                ]
            ),
        )
    )
    source = make_source()
    assert isinstance(source, CategoryExplorer)
    counts = await source.explore_categories(query(), City.LIMASSOL)
    assert counts == {PHONES: 2, "telephones/accessories": 1}
    await source.explore_categories(query(), City.LIMASSOL)
    assert route.call_count == 1


# --- orchestrator and service --------------------------------------------------------------


async def test_orchestrator_passes_the_category_and_enforces_it() -> None:
    phone = make_listing("iPhone 13 128GB", external_id="a", category=PHONES)
    case = make_listing(
        "iPhone 13 128GB case lot", external_id="b", category="telephones/accessories"
    )
    post = make_listing("iPhone 13 128GB", source="telegram", external_id="c")  # no category
    bazaraki = FakeSource("bazaraki", [phone, case])
    telegram = FakeSource("telegram", [post])

    outcome = await SearchOrchestrator([bazaraki, telegram]).search(
        ExpandedQuery(original="iphone 13", normalized="iphone 13"),
        City.LIMASSOL,
        category=PHONES,
    )
    assert bazaraki.calls[0][2].category == PHONES and telegram.calls[0][2].category == PHONES
    assert outcome.category == PHONES
    assert {li.external_id for li in outcome.listings} == {"a", "c"}  # the accessory is dropped


async def test_no_category_means_nothing_is_dropped() -> None:
    source = FakeSource("bazaraki", [make_listing("iPhone 13", external_id="a", category=PHONES)])
    outcome = await SearchOrchestrator([source]).search(
        ExpandedQuery(original="iphone 13", normalized="iphone 13"), City.LIMASSOL
    )
    assert source.calls[0][2].category is None and outcome.category is None
    assert len(outcome.listings) == 1


class ExploringSource(FakeSource):
    def __init__(self, counts: dict[str, int] | Exception) -> None:
        super().__init__("bazaraki", [])
        self.counts = counts

    async def explore_categories(self, query: ExpandedQuery, city: City | None) -> dict[str, int]:
        if isinstance(self.counts, Exception):
            raise self.counts
        return self.counts


class EchoExpander:
    async def expand(self, text: str) -> ExpandedQuery:
        return ExpandedQuery(original=text, normalized=text.lower())


def service_with(*explorers: ExploringSource) -> SearchService:
    return SearchService(
        EchoExpander(), SearchOrchestrator(list(explorers)), explorers=list(explorers)
    )


USER = UserProfile(telegram_id=1, city=City.LIMASSOL)


async def test_plan_asks_when_the_results_are_split() -> None:
    plan = await service_with(ExploringSource(PROPERTY)).plan_category(USER, "3 bedroom apartment")
    assert isinstance(plan.decision, Ask) and plan.decision.prefix is None
    assert plan.intent is None and plan.query.original == "3 bedroom apartment"


async def test_plan_uses_the_intent_from_the_text() -> None:
    plan = await service_with(ExploringSource(PROPERTY)).plan_category(
        USER, "3 bedroom flat to rent"
    )
    assert plan.intent == "rent"
    assert isinstance(plan.decision, Ask) and plan.decision.prefix == RENT


async def test_plan_survives_a_failing_explorer() -> None:
    plan = await service_with(ExploringSource(SourceError("blocked"))).plan_category(USER, "iphone")
    assert plan.decision == Resolved(None) and plan.counts == {}


async def test_plan_without_explorers_searches_everywhere() -> None:
    service = SearchService(EchoExpander(), SearchOrchestrator([]))
    assert (await service.plan_category(USER, "iphone")).decision == Resolved(None)


async def test_plan_merges_several_explorers() -> None:
    a, b = ExploringSource({PHONES: 5}), ExploringSource({PHONES: 5, "telephones/accessories": 5})
    plan = await service_with(a, b).plan_category(USER, "iphone")
    assert plan.counts == {PHONES: 10, "telephones/accessories": 5}
