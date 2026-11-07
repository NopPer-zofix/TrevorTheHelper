"""Rule-based query expansion: used when the LLM is unavailable (no key, timeout, API error).

Deliberately small and deterministic: tokenise, drop filler words, detect spec tokens
(`128gb`, `26"`), add EN<->RU variants for common items and category-based negative terms.
"""

from __future__ import annotations

import re

from aggregator.domain.lexicon import (
    FORMS_OF,
    GROUPS,
    PROPERTY_KINDS,
    canonical_token,
    category_of,
    normalize_rooms,
)
from aggregator.domain.models import ExpandedQuery
from aggregator.query.normalize import clean_expansion, normalize_input

_STOP_WORDS = frozenset(
    {
        # English
        "a", "an", "the", "for", "in", "of", "with", "and", "or", "to", "on", "at", "me",
        "buy", "sale", "sell", "selling", "want", "wanted", "looking", "need", "please",
        "cheap", "used", "second", "hand", "secondhand", "near", "cyprus",
        # Russian
        "в", "на", "и", "для", "с", "по", "из", "от", "у", "к", "мне", "нужен", "нужна",
        "купить", "куплю", "продам", "продается", "продаётся", "б", "бу", "дешево",
        "дёшево", "кипр", "кипре", "кипра", "недорого",
    }
)  # fmt: skip

_GROUP_OF: dict[str, tuple[str, tuple[str, ...]]] = {
    word: (category, group) for category, group in GROUPS for word in group
}
# These categories are handled by dedicated rules, not by the one-word swaps.
_NO_SWAP = frozenset({"property", "intent", "place"})

_BRANDS: dict[str, str] = {
    "iphone": "Apple", "айфон": "Apple", "ipad": "Apple", "айпад": "Apple",
    "macbook": "Apple", "макбук": "Apple", "airpods": "Apple", "apple": "Apple",
    "samsung": "Samsung", "самсунг": "Samsung",
    "xiaomi": "Xiaomi", "сяоми": "Xiaomi", "ксиоми": "Xiaomi",
    "huawei": "Huawei", "хуавей": "Huawei",
    "sony": "Sony", "сони": "Sony",
    "lenovo": "Lenovo", "asus": "Asus", "dell": "Dell", "hp": "HP", "lg": "LG",
    "dyson": "Dyson", "ikea": "IKEA", "икея": "IKEA", "nike": "Nike",
}  # fmt: skip

_GENERIC_NEGATIVES = ("wanted", "wtb", "куплю", "ищу")
_CATEGORY_NEGATIVES: dict[str, tuple[str, ...]] = {
    "phone": ("case", "cover", "charger", "чехол", "защитное стекло", "зарядка", "запчасти"),
    "tablet": ("case", "cover", "charger", "чехол", "зарядка", "запчасти"),
    "laptop": ("bag", "case", "charger", "сумка", "чехол", "зарядка", "запчасти"),
    "audio": ("case", "чехол"),
    "tv": ("remote", "bracket", "пульт", "кронштейн"),
    "bike": ("helmet", "lock", "pump", "шлем", "замок", "насос", "запчасти"),
}

_SPEC_TOKEN = re.compile(
    r"^\d+(?:[.,]\d+)?(?:gb|tb|mb|гб|тб|мб|inch|cm|см|kg|кг|l|л|w|вт|mah|мач)$"
)
_UNIT_SPLIT = re.compile(r"^(\d+)(gb|tb|гб|тб)$")
_UNIT_JOIN = re.compile(r"(\d+) (gb|tb|гб|тб)\b")


def _core_tokens(normalized: str) -> list[str]:
    tokens = [t for t in normalized.split() if t not in _STOP_WORDS]
    return tokens or normalized.split()


def _variants(tokens: list[str]) -> list[str]:
    variants: list[str] = []

    # EN <-> RU swaps, one glossary token at a time (keeps the rest of the query intact).
    for index, token in enumerate(tokens):
        entry = _GROUP_OF.get(token)
        if entry is None or entry[0] in _NO_SWAP:
            continue
        for alternative in entry[1]:
            if alternative != token:
                variants.append(" ".join([*tokens[:index], alternative, *tokens[index + 1 :]]))

    # "128gb" <-> "128 gb" spelling.
    joined = " ".join(tokens)
    spaced = " ".join(
        part for token in tokens for part in (_UNIT_SPLIT.sub(r"\1 \2", token)).split(" ")
    )
    if spaced != joined:
        variants.append(spaced)
    unspaced = _UNIT_JOIN.sub(r"\1\2", joined)
    if unspaced != joined:
        variants.append(unspaced)
    return variants


_CYRILLIC = re.compile(r"[а-я]")
_ROOMS = re.compile(r"^\d+$")

# English search phrases per kind of property (first = primary, the rest are variants).
_KIND_EN = {
    "apartment": ("apartment", "flat"),
    "house": ("house",),
    "villa": ("villa",),
    "studio": ("studio",),
    "penthouse": ("penthouse",),
    "townhouse": ("townhouse",),
    "room": ("room",),
}


def _ru_bedrooms(count: int) -> str:
    if count == 1:
        return "спальня"
    return "спальни" if 2 <= count <= 4 else "спален"


def _ru_phrases(kind: str, rooms: int | None) -> list[str]:
    """How Russian-speaking sellers write the same ad title."""
    if kind == "apartment":
        if rooms is None:
            return ["квартира"]
        return [f"{rooms}-комнатная квартира", f"квартира {rooms} {_ru_bedrooms(rooms)}"]
    simple = {
        "studio": "студия",
        "penthouse": "пентхаус",
        "townhouse": "таунхаус",
        "room": "комната",
    }
    if kind in simple:
        return [simple[kind]]
    noun = "дом" if kind == "house" else "вилла"
    return [noun] if rooms is None else [f"{noun} {rooms} {_ru_bedrooms(rooms)}"]


def _expand_property(text: str, tokens: list[str], canon: list[str], kind: str) -> ExpandedQuery:
    """ "3-х комнатная квартира" and "3-bedroom apartment" become the SAME query.

    The primary phrase is English ("3 bedroom apartment") whatever language was typed; the variants
    are the English synonym ("3 bedroom flat") and the Russian way to write it ("3-комнатная
    квартира"). Rent / sale words are intent (they pick the category), not text to match, so they
    are dropped here; place names are translated; any other word is kept as typed.
    """
    rooms: int | None = None
    en_extras: list[str] = []
    ru_extras: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if _ROOMS.match(token) and index + 1 < len(tokens) and canon[index + 1] == "bedroom":
            rooms = int(token)
            index += 2
            continue
        if (
            canon[index] in PROPERTY_KINDS
            or canon[index] == "bedroom"
            or category_of(token) == "intent"
        ):
            index += 1
            continue
        if category_of(token) == "place":
            forms = FORMS_OF[token]
            en_extras.append(forms[0])
            ru_extras.append(next((f for f in forms if _CYRILLIC.match(f)), forms[0]))
        else:
            en_extras.append(token)
            ru_extras.append(token)
        index += 1

    lead = [f"{rooms} bedroom"] if rooms else []
    en_nouns = _KIND_EN[kind]
    primary = " ".join([*lead, en_nouns[0], *en_extras])
    variants = [" ".join([*lead, noun, *en_extras]) for noun in en_nouns[1:]]
    variants += [" ".join([phrase, *ru_extras]) for phrase in _ru_phrases(kind, rooms)]
    return clean_expansion(
        ExpandedQuery(
            original=text,
            normalized=primary,
            variants=variants,
            negative_terms=list(_GENERIC_NEGATIVES),
            category_hint="property",
        )
    )


def expand_with_rules(text: str) -> ExpandedQuery:
    normalized_input = normalize_input(text)

    # Property searches get their own handling: room counts, rent/sale words and the Russian
    # phrasing ("3-х комнатная квартира") all describe the same thing as "3 bedroom apartment".
    room_tokens = _core_tokens(normalize_rooms(normalized_input))
    room_canon = [canonical_token(t) for t in room_tokens]
    kind = next((c for c in room_canon if c in PROPERTY_KINDS), None)
    if kind is not None:
        return _expand_property(text, room_tokens, room_canon, kind)

    tokens = _core_tokens(normalized_input)
    normalized = " ".join(tokens)

    brand = next((_BRANDS[t] for t in tokens if t in _BRANDS), None)
    specs = [t for t in tokens if _SPEC_TOKEN.match(t)]
    category = next((_GROUP_OF[t][0] for t in tokens if t in _GROUP_OF), None)
    negatives = [*_CATEGORY_NEGATIVES.get(category or "", ()), *_GENERIC_NEGATIVES]

    return clean_expansion(
        ExpandedQuery(
            original=text,
            normalized=normalized,
            brand=brand,
            specs=specs,
            variants=_variants(tokens),
            negative_terms=negatives,
            category_hint=category,
        )
    )
