"""Rule-based query expansion: used when the LLM is unavailable (no key, timeout, API error).

Deliberately small and deterministic: tokenise, drop filler words, detect spec tokens
(`128gb`, `26"`), add EN<->RU variants for common items and category-based negative terms.
"""

from __future__ import annotations

import re

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

# Equivalent spellings / translations of common items. A token matching any entry of a group
# produces variants using the other entries. The first field is the category.
_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("phone", ("iphone", "айфон", "айфона")),
    ("phone", ("smartphone", "смартфон")),
    ("phone", ("phone", "телефон", "мобильный")),
    ("phone", ("samsung", "самсунг")),
    ("phone", ("xiaomi", "сяоми", "ксиоми")),
    ("phone", ("huawei", "хуавей")),
    ("tablet", ("ipad", "айпад")),
    ("tablet", ("tablet", "планшет")),
    ("laptop", ("laptop", "ноутбук")),
    ("laptop", ("macbook", "макбук")),
    ("audio", ("airpods", "аирподс", "эирподс")),
    ("audio", ("headphones", "наушники")),
    ("console", ("playstation", "плейстейшн", "плейстейшен")),
    ("console", ("xbox", "иксбокс")),
    ("tv", ("tv", "телевизор")),
    ("camera", ("camera", "фотоаппарат", "камера")),
    ("appliance", ("fridge", "refrigerator", "холодильник")),
    ("appliance", ("microwave", "микроволновка", "микроволновая")),
    ("bike", ("bike", "bicycle", "велосипед")),
    ("bike", ("scooter", "самокат")),
    ("furniture", ("sofa", "couch", "диван")),
    ("furniture", ("table", "стол")),
    ("furniture", ("chair", "стул")),
    ("furniture", ("bed", "кровать")),
    ("furniture", ("wardrobe", "шкаф")),
    ("watch", ("watch", "часы")),
)

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

_GROUP_OF: dict[str, tuple[str, tuple[str, ...]]] = {
    word: (category, group) for category, group in _GROUPS for word in group
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
        if entry is None:
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


def expand_with_rules(text: str) -> ExpandedQuery:
    normalized_input = normalize_input(text)
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
