"""City enum and text-based city detection (English, Russian, common transliterations)."""

from __future__ import annotations

import re
from enum import StrEnum


class City(StrEnum):
    NICOSIA = "nicosia"
    LIMASSOL = "limassol"
    LARNACA = "larnaca"
    PAPHOS = "paphos"
    FAMAGUSTA = "famagusta"
    ALL_CYPRUS = "all"  # a search scope only; never the city of a concrete listing
    UNKNOWN = "unknown"  # a listing whose city could not be determined


SELECTABLE_CITIES: tuple[City, ...] = (
    City.NICOSIA,
    City.LIMASSOL,
    City.LARNACA,
    City.PAPHOS,
    City.FAMAGUSTA,
    City.ALL_CYPRUS,
)

# Prefix patterns (matched at a word start, so Russian case endings like "в Лимассоле"
# and "из Пафоса" are covered by the stem). Includes well-known towns of each district.
_CITY_STEMS: dict[City, tuple[str, ...]] = {
    City.NICOSIA: (
        "nicosia",
        "lefkosia",
        "lefkosa",
        "никоси",
        "никоз",
        "лефкоси",
        "лефкоз",
        "левкоси",
        "strovolos",
        "стровол",
        "lakatamia",
        "лакатами",
        "aglantzia",
        "агланди",
        "engomi",
        "egkomi",
        "энгоми",
        "эгкоми",
    ),
    City.LIMASSOL: (
        "limassol",
        "limasol",
        "lemesos",
        "лимассол",
        "лимасол",
        "лемесос",
        "лемесо",
        "лемес ",
        "germasogeia",
        "гермасойя",
        "гермасогия",
        "mesa geitonia",
        "agios athanasios",
    ),
    City.LARNACA: (
        "larnaca",
        "larnaka",
        "larnaga",
        "ларнак",
        "aradippou",
        "арадиппу",
        "oroklini",
        "орокли",
        "livadia",
        "ливадия",
    ),
    City.PAPHOS: (
        "paphos",
        "pafos",
        "пафос",
        "пафо",
        "kato paphos",
        "peyia",
        "пейя",
        "polis chrysochous",
    ),
    City.FAMAGUSTA: (
        "famagusta",
        "ammochostos",
        "фамагуст",
        "амохост",
        "аммохост",
        "ayia napa",
        "agia napa",
        "aya napa",
        "айя-напа",
        "айя напа",
        "ayia-napa",
        "protaras",
        "протарас",
        "paralimni",
        "паралимни",
    ),
}

_PATTERNS: list[tuple[City, re.Pattern[str]]] = [
    (city, re.compile(r"(?<!\w)(?:" + "|".join(re.escape(s) for s in stems) + ")"))
    for city, stems in _CITY_STEMS.items()
]


def _normalize(text: str) -> str:
    return text.lower().replace("ё", "е")


def detect_city(text: str) -> City:
    """Return the city mentioned in `text`, or `City.UNKNOWN`.

    If several cities are mentioned, the one mentioned first wins (listings usually state
    their location before delivery options).
    """
    haystack = _normalize(text)
    best: tuple[int, City] | None = None
    for city, pattern in _PATTERNS:
        match = pattern.search(haystack)
        if match and (best is None or match.start() < best[0]):
            best = (match.start(), city)
    return best[1] if best else City.UNKNOWN


def city_matches(listing_city: City, selected: City | None) -> bool:
    """Whether a listing belongs in results for the user's selected city.

    "All Cyprus" (or no selection) includes everything, including unknown-city listings.
    A specific city only includes listings positively detected in that city.
    """
    if selected is None or selected is City.ALL_CYPRUS:
        return True
    return listing_city is selected
