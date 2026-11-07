"""The marketplace category catalog (Bazaraki's two-level tree) and helpers around it.

A category is identified by its URL path without slashes at the ends, e.g.
"real-estate-to-rent/apartments-flats". Only the data lives in `category_data.py`.
"""

from __future__ import annotations

from dataclasses import dataclass

from aggregator.domain.category_data import CATEGORY_ROWS, EXCLUDED_PATHS

MAX_DEPTH = 2
SEPARATOR = " › "


@dataclass(frozen=True)
class Category:
    path: str
    en: str
    ru: str | None = None

    @property
    def depth(self) -> int:
        return self.path.count("/") + 1

    def label(self, language: str) -> str:
        return (self.ru if language == "ru" else None) or self.en


CATALOG: dict[str, Category] = {path: Category(path, en, ru) for path, en, ru in CATEGORY_ROWS}


def get_category(path: str | None) -> Category | None:
    return CATALOG.get(path) if path else None


def is_known_category(path: str | None) -> bool:
    return path in CATALOG if path else False


def is_offered(path: str) -> bool:
    """Whether a category may be offered as an answer to a question (adult ones never are)."""
    return path in CATALOG and path not in EXCLUDED_PATHS


def parent_of(path: str) -> str | None:
    return path.rsplit("/", 1)[0] if "/" in path else None


def normalize_path(raw: str | None) -> str | None:
    """Reduce any category path (e.g. "telephones/mobile-phones/iphone") to the deepest known
    prefix within `MAX_DEPTH` levels ("telephones/mobile-phones"); None if even the first level
    is unknown."""
    if not raw:
        return None
    parts = [p for p in raw.strip("/").split("/") if p][:MAX_DEPTH]
    while parts:
        candidate = "/".join(parts)
        if candidate in CATALOG:
            return candidate
        parts.pop()
    return None


def category_label(path: str | None, language: str = "en") -> str:
    """ "Real Estate to rent › Apartments, flats" (or just the top level for a top-level path)."""
    if not path:
        return ""
    names: list[str] = []
    parts = path.split("/")
    for depth in range(1, len(parts) + 1):
        category = CATALOG.get("/".join(parts[:depth]))
        names.append(category.label(language) if category else parts[depth - 1])
    return SEPARATOR.join(names)


def short_label(path: str, language: str = "en") -> str:
    """Only the last level: "Apartments, flats"."""
    category = CATALOG.get(path)
    return category.label(language) if category else path.rsplit("/", 1)[-1]
