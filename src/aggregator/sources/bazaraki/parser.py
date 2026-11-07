"""Turn a Bazaraki search-results HTML page into `Listing` objects (no network here)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from aggregator.domain.categories import normalize_path
from aggregator.domain.cities import City, detect_city
from aggregator.domain.models import Listing
from aggregator.domain.pricing import parse_price
from aggregator.sources.base import SourceError
from aggregator.sources.bazaraki import selectors as sel

SOURCE_NAME = "bazaraki"

_RELATIVE_RE = re.compile(r"(\d+)\s+(second|minute|hour|day|week|month|year)s?\s+ago", re.I)
_UNIT_SECONDS = {"second": 1, "minute": 60, "hour": 3600}
_UNIT_DAYS = {"day": 1, "week": 7, "month": 30, "year": 365}


@dataclass(frozen=True)
class ParsedPage:
    listings: list[Listing]
    has_next_page: bool


def parse_published(text: str | None, now: datetime) -> datetime:
    """Approximate a post time from Bazaraki's relative text ("3 days ago", "Yesterday").

    Months count as 30 days. Anything unrecognised falls back to `now`.
    """
    if not text:
        return now
    lowered = text.strip().lower()
    if lowered == "today":
        return now
    if lowered == "yesterday":
        return now - timedelta(days=1)
    match = _RELATIVE_RE.search(lowered)
    if not match:
        return now
    count, unit = int(match.group(1)), match.group(2).lower()
    if unit in _UNIT_SECONDS:
        return now - timedelta(seconds=count * _UNIT_SECONDS[unit])
    return now - timedelta(days=count * _UNIT_DAYS[unit])


def _flight_stream(html: str) -> str:
    chunks: list[str] = []
    for match in sel.FLIGHT_PUSH_RE.finditer(html):
        try:
            chunks.append(json.loads(match.group(1)))
        except ValueError:
            continue
    return "".join(chunks)


def extract_adverts(html: str) -> list[dict[str, Any]] | None:
    """The advert objects embedded in the page, or None if the page has no such data."""
    stream = _flight_stream(html)
    decoder = json.JSONDecoder()
    position = stream.find(sel.ADVERTS_KEY)
    while position != -1:
        start = position + len(sel.ADVERTS_KEY)
        try:
            value, _ = decoder.raw_decode(stream, start)
        except ValueError:
            value = None
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        position = stream.find(sel.ADVERTS_KEY, start)
    return None


def advert_category(advert: dict[str, Any]) -> str | None:
    """The advert's category path reduced to the catalog, e.g. "telephones/mobile-phones"."""
    rubric = advert.get(sel.F_RUBRIC)
    if not isinstance(rubric, dict):
        return None
    ancestors = rubric.get(sel.F_ANCESTORS)
    if not isinstance(ancestors, list):
        return None
    # The advert's own category is the rubric itself; `ancestors` are only its parents. For a flat
    # ad: ancestors = [real-estate-to-rent], rubric = apartments-flats. For an iPhone ad:
    # ancestors = [telephones, mobile-phones, iphone], rubric = iphone-13 (cut off below).
    slugs = [a.get(sel.F_SLUG) for a in ancestors if isinstance(a, dict)]
    slugs.append(rubric.get(sel.F_SLUG))
    return normalize_path("/".join(s for s in slugs if isinstance(s, str) and s))


def _to_listing(
    advert: dict[str, Any], *, now: datetime, scoped_city: City | None
) -> Listing | None:
    raw_id = advert.get(sel.F_ID)
    url = advert.get(sel.F_URL)
    title = advert.get(sel.F_TITLE)
    if raw_id is None or not url or not title:
        return None  # not a regular advert (promo slot, layout change): skip rather than guess

    city = detect_city(str(advert.get(sel.F_LOCATION) or ""))
    if city is City.UNKNOWN and scoped_city is not None:
        city = scoped_city  # the request was already filtered to this district

    amount = parse_price(str(advert.get(sel.F_PRICE_NUMBER) or "")) or parse_price(
        str(advert.get(sel.F_PRICE_TEXT) or "")
    )
    currency = str(advert.get(sel.F_CURRENCY) or "EUR").upper() if amount else None
    description = str(advert.get(sel.F_DESCRIPTION) or "").strip() or None

    return Listing(
        source=SOURCE_NAME,
        external_id=str(raw_id),
        url=sel.BASE_URL + url if str(url).startswith("/") else str(url),
        title=str(title).strip(),
        description=description,
        price_amount=amount,
        currency=currency,
        city=city,
        posted_at=parse_published(advert.get(sel.F_PUBLISHED), now),
        category=advert_category(advert),
    )


def parse_search_page(
    html: str,
    *,
    now: datetime,
    page: int = 1,
    searched_city: City | None = None,
) -> ParsedPage:
    """Parse one results page.

    `searched_city` is the district the request was scoped to; it is used for listings whose
    location text names no recognisable city. Raises `SourceError` if the page carries no advert
    data at all (blocked / captcha / markup changed) so that failure is visible, not silent.
    """
    adverts = extract_adverts(html)
    if adverts is None:
        raise SourceError("bazaraki page has no recognisable advert data (blocked or changed?)")

    scoped = searched_city if searched_city not in (None, City.ALL_CYPRUS) else None
    listings = [
        listing
        for advert in adverts
        if (listing := _to_listing(advert, now=now, scoped_city=scoped)) is not None
    ]
    page_numbers = [int(n) for n in sel.PAGE_LINK_RE.findall(html)]
    return ParsedPage(listings=listings, has_next_page=any(n > page for n in page_numbers))
