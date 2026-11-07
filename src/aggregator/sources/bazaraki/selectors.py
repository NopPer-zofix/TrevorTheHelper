"""Everything that knows about Bazaraki's page structure lives here.

If the site changes, this is the only module that should need editing (plus the fixtures).
These were found by inspecting the live site (HTML and the embedded Next.js data) on 2026-11-03.

Why the embedded payload and not the DOM: the grid view and the city-scoped list view use
different card components (`CardGridDesktop` vs `BigAdCard`), but both pages embed the same
advert objects in the Next.js flight data, with named fields. We read that server-rendered data
from the HTML document itself; we never call the (robots.txt-disallowed) `/api` endpoints.
"""

from __future__ import annotations

import re

BASE_URL = "https://www.bazaraki.com"

# --- Embedded Next.js flight data ----------------------------------------------------------
# <script>self.__next_f.push([1,"<json-escaped chunk>"])</script>: chunks concatenate into one
# stream.
FLIGHT_PUSH_RE = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)')
ADVERTS_KEY = '"adverts":'

# Field names inside each advert object.
F_ID = "id"
F_TITLE = "title"
F_DESCRIPTION = "description"
F_PRICE_TEXT = "price"  # "€250" or text such as "Negotiable"
F_PRICE_NUMBER = "price_without_currency"  # "250" (preferred when present)
F_CURRENCY = "currency"
F_PUBLISHED = "published"  # relative: "3 days ago", "Yesterday"
F_URL = "url"  # "/adv/<id>_<slug>/"
F_LOCATION = "location"  # "Limassol — Limassol Marina"
F_RUBRIC = "rubric"  # {"slug": "iphone-13", "ancestors": [{"slug": "telephones"}, ...]}
F_ANCESTORS = "ancestors"
F_SLUG = "slug"

# --- Pagination (links rendered in the HTML, `...&page=N`) ----------------------------------------
PAGE_LINK_RE = re.compile(r"[?&;]page=(\d+)")

# --- Search URLs ---------------------------------------------------------------------------------
# City filter is path based. Never use `attrs_*` query params or /api: robots.txt disallows them.
DISTRICT_SLUGS: dict[str, str] = {
    "nicosia": "lefkosia-district-nicosia",
    "limassol": "lemesos-district-limassol",
    "larnaca": "larnaka-district-larnaca",
    "paphos": "pafos-district-paphos",
    "famagusta": "ammochostos-district",
}


def search_path(city_value: str | None, category: str | None = None) -> str:
    """`/search/[<district>/]`, or `/<category>/[<district>/]` to search inside a category.

    `category` must be a known catalog path (the caller checks), so no user text ends up in the URL.
    """
    slug = DISTRICT_SLUGS.get(city_value or "")
    base = f"/{category.strip('/')}/" if category else "/search/"
    return f"{base}{slug}/" if slug else base
