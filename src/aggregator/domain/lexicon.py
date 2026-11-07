"""Shared English / Russian vocabulary: why "3-х комнатная квартира" == "3-bedroom apartment".

Two jobs, both language-neutral:
- `canonical_token`: every spelling, translation and inflection of a concept maps to one canonical
  English token (флат / flat / квартира / apartments -> "apartment"). The relevance filter compares
  canonical tokens, so a Russian query matches an English ad and the other way round.
- `normalize_rooms`: room counts are written in many ways ("3-х комнатная", "трёхкомнатная",
  "3 спальни", "3BR", "three bedroom", "3 bed flat"); all become "3 bedroom".

A group is (category, forms): the FIRST form is the canonical one. All forms are lower case, with
"е" for "ё" (tokens are folded the same way before lookup).

Caveat worth knowing: a Russian "3-комнатная" counts rooms (often 2 bedrooms + a living room) while
"3-bedroom" counts bedrooms. Listings in Cyprus are mostly written the second way even in Russian,
and users expect the two phrases to meet, so they are treated as equal.
"""

from __future__ import annotations

import re

from aggregator.domain.areas import AREAS

# (category, (canonical, other forms...)). Categories feed the negative-term lists in
# query/fallback.py; "property", "intent" and "place" are handled by dedicated rules there.
_BASE_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    # --- phones, computers, audio, gaming, TV, cameras ---------------------------------------
    ("phone", ("iphone", "айфон", "айфона", "айфоны")),
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
    ("audio", ("speaker", "колонка", "колонки")),
    ("console", ("playstation", "плейстейшн", "плейстейшен")),
    ("console", ("xbox", "иксбокс")),
    ("tv", ("tv", "телевизор")),
    ("camera", ("camera", "фотоаппарат", "камера")),
    ("computer", ("monitor", "монитор")),
    ("computer", ("printer", "принтер")),
    ("computer", ("router", "роутер")),
    # --- home ---------------------------------------------------------------------------------
    ("appliance", ("fridge", "refrigerator", "холодильник")),
    ("appliance", ("microwave", "микроволновка", "микроволновая")),
    ("appliance", ("dishwasher", "посудомойка", "посудомоечная")),
    ("appliance", ("vacuum", "пылесос")),
    ("appliance", ("oven", "духовка", "духовой")),
    ("appliance", ("kettle", "чайник")),
    ("appliance", ("conditioner", "кондиционер")),
    ("furniture", ("sofa", "couch", "диван")),
    ("furniture", ("table", "стол")),
    ("furniture", ("chair", "стул")),
    ("furniture", ("armchair", "кресло")),
    ("furniture", ("bed", "кровать")),
    ("furniture", ("mattress", "матрас")),
    ("furniture", ("wardrobe", "шкаф")),
    # --- transport, kids, accessories ---------------------------------------------------------
    ("bike", ("bike", "bicycle", "велосипед")),
    ("bike", ("scooter", "самокат")),
    ("car", ("car", "авто", "автомобиль", "машина")),
    ("car", ("motorbike", "motorcycle", "мотоцикл")),
    ("car", ("toyota", "тойота")),
    ("car", ("mercedes", "мерседес")),
    ("car", ("bmw", "бмв")),
    ("car", ("audi", "ауди")),
    ("car", ("volkswagen", "фольксваген")),
    ("car", ("nissan", "ниссан")),
    ("car", ("honda", "хонда")),
    ("car", ("hyundai", "хендай", "хундай")),
    ("car", ("kia", "киа")),
    ("car", ("mazda", "мазда")),
    ("kids", ("stroller", "pram", "pushchair", "коляска", "коляску")),
    ("kids", ("toy", "toys", "игрушка", "игрушки")),
    ("watch", ("watch", "часы")),
    # --- property -----------------------------------------------------------------------------
    ("property", ("apartment", "apartments", "flat", "flats", "квартира", "квартиры", "квартиру",
                  "квартире", "квартир", "апартамент", "апартаменты", "апартаментов")),
    ("property", ("house", "houses", "дом", "дома", "дому", "доме", "домов", "домом", "домик",
                  "коттедж")),
    ("property", ("villa", "villas", "вилла", "виллы", "виллу", "вилле")),
    ("property", ("studio", "studios", "студия", "студии", "студию")),
    ("property", ("penthouse", "penthouses", "пентхаус", "пентхауса")),
    ("property", ("townhouse", "townhouses", "таунхаус", "таунхауса")),
    ("property", ("room", "rooms", "комната", "комнаты", "комнату", "комнате")),
    ("property", ("bedroom", "bedrooms", "br", "bdr", "спальня", "спальни", "спальню", "спален",
                  "спальный", "спальная", "спальные")),
    # --- what the user wants to do (answers the rent-or-buy question, never searched as text) --
    ("intent", ("rent", "rental", "rentals", "аренда", "аренды", "аренду", "сдается", "сдам",
                "снять", "сниму", "посуточно")),
    # --- places ------------------------------------------------------------------------------
    ("place", ("limassol", "лимассол", "лимасол", "лемесос", "лемесо", "lemesos")),
    ("place", ("nicosia", "никосия", "никосии", "никозия", "лефкосия", "лефкоза", "левкосия",
                "lefkosia", "lefkosa")),
    ("place", ("larnaca", "larnaka", "ларнака", "ларнаке", "ларнаки")),
    ("place", ("paphos", "pafos", "пафос", "пафосе")),
    ("place", ("famagusta", "фамагуста", "фамагусте", "ammochostos", "аммохостос", "амохостос")),
)  # fmt: skip


def _area_groups() -> tuple[tuple[str, tuple[str, ...]], ...]:
    """One group per single-word area, so "Гермасойя" and "Yermasoyia" meet "Germasogeia"."""
    groups = []
    for area in AREAS:
        canonical = area.name.lower()
        if " " in canonical:
            continue
        forms = [canonical, *(a.lower().replace("ё", "е") for a in area.aliases)]
        singles = tuple(dict.fromkeys(f for f in forms if " " not in f and "-" not in f))
        groups.append(("place", singles))
    return tuple(groups)


GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (*_BASE_GROUPS, *_area_groups())

# Only lowercase words with "е" (no "ё") may appear above; checked by the tests.
CANONICAL: dict[str, str] = {}
CATEGORY_OF: dict[str, str] = {}
FORMS_OF: dict[str, tuple[str, ...]] = {}  # any form -> its whole group
for _category, _forms in GROUPS:
    for _form in _forms:
        CANONICAL.setdefault(_form, _forms[0])
        CATEGORY_OF.setdefault(_form, _category)
        FORMS_OF.setdefault(_form, _forms)

# The kinds of property a query can be about (canonical tokens).
PROPERTY_KINDS = frozenset(
    {"apartment", "house", "villa", "studio", "penthouse", "townhouse", "room"}
)


# Regular Russian case endings: a word that is a known stem plus one of these is that word
# ("велосипеды", "квартирами"). Anything else after the stem ("домофон") is a different word.
_RU_ENDINGS = frozenset(
    {"", "а", "я", "ы", "и", "у", "ю", "е", "о", "ь", "ой", "ей", "ом", "ем", "ам", "ям", "ами",
     "ями", "ах", "ях", "ов", "ев", "ью"}
)  # fmt: skip
_RU_VOWEL_ENDINGS = "аяыиуеоюь"
_MIN_STEM = 4  # shorter stems ("час" from "часы", "авт") would swallow unrelated words
_CYRILLIC = re.compile(r"[а-я]")


def _stem_of(form: str) -> str:
    return form[:-1] if form[-1] in _RU_VOWEL_ENDINGS else form


_RU_STEMS: dict[str, str] = {}
for _form, _canon in CANONICAL.items():
    if _CYRILLIC.match(_form) and len(_stem_of(_form)) >= _MIN_STEM:
        _RU_STEMS.setdefault(_stem_of(_form), _canon)


def canonical_token(token: str) -> str:
    """The canonical English token for any known spelling, translation or regular inflection."""
    found = CANONICAL.get(token)
    if found is not None:
        return found
    if token.endswith("s") and token[:-1] in CANONICAL:  # bikes, phones, villas
        return CANONICAL[token[:-1]]
    if _CYRILLIC.match(token):
        for cut in range(0, 4):  # longest stem first
            stem = token[: len(token) - cut]
            if len(stem) >= _MIN_STEM and stem in _RU_STEMS and token[len(stem) :] in _RU_ENDINGS:
                return _RU_STEMS[stem]
    return token


def category_of(token: str) -> str | None:
    return CATEGORY_OF.get(token)


# --- room counts -------------------------------------------------------------------------------

_EN_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7}
_RU_NUMBER_STEMS = {
    "одно": 1, "двух": 2, "трех": 3, "четырех": 4, "пяти": 5, "шести": 6, "семи": 7,
}  # fmt: skip

_PROPERTY_WORDS = (
    r"apartments?|flats?|house|villa|studio|penthouse|townhouse|квартир\w*|дом\w*|вилл\w*"
)
_EN_NUMBER_WORDS = "|".join(_EN_NUMBERS)
_RU_NUMBER_ALT = "|".join(_RU_NUMBER_STEMS)

# "three bedroom", "three-bedroom"
_EN_WORD_ROOMS = re.compile(rf"\b({_EN_NUMBER_WORDS})[\s-]*(?:bedrooms?|bed|br)\b")
# "трехкомнатная", "двухспальная"
_RU_WORD_ROOMS = re.compile(rf"\b({_RU_NUMBER_ALT})[\s-]*(?:комнатн\w*|спальн\w*)")
# "3 bedroom(s)", "3-bedroom", "3BR", "3 bdr"
_EN_DIGIT_ROOMS = re.compile(r"\b(\d+)\s*-?\s*(?:bedrooms?|br|bdr|bd)\b")
# "3 bed flat" / "3-bed house": "bed" only counts when a property word follows (not "2 bed sheets")
_EN_BED_ROOMS = re.compile(rf"\b(\d+)\s*-?\s*beds?\b(?=\s+(?:{_PROPERTY_WORDS}))")
# "3-х комнатная", "3-комнатная", "3х комн.", "3 комнаты", "3 спальни", "3-спальный"
_RU_DIGIT_ROOMS = re.compile(
    r"\b(\d+)\s*-?\s*(?:х|x|ех|ти|и)?\s*-?\s*(?:комнатн\w*|комнат\w*|комн\b|спальн\w*|спален)"
)
# slang "3к квартира"
_RU_SHORT_ROOMS = re.compile(rf"\b(\d+)\s*к\b(?=\s+(?:{_PROPERTY_WORDS}))")
_FLAT_SCREEN = re.compile(r"\bflat[\s-]*(screen|tv|panel|monitor|pack|iron|shoes)\b")


def fold(text: str) -> str:
    """Casefold and fold "ё" to "е"; the form every lexicon lookup expects."""
    return text.casefold().replace("ё", "е")


def normalize_rooms(text: str) -> str:
    """Rewrite every way of stating a room count as "N bedroom" ("3-х комнатная" -> "3 bedroom").

    Also protects "flat screen" / "flat tv" from being read as the apartment "flat".
    """
    out = fold(text)
    out = _FLAT_SCREEN.sub(lambda m: f"flat{m.group(1)}", out)
    out = _EN_WORD_ROOMS.sub(lambda m: f"{_EN_NUMBERS[m.group(1)]} bedroom", out)
    out = _RU_WORD_ROOMS.sub(lambda m: f"{_RU_NUMBER_STEMS[m.group(1)]} bedroom", out)
    for pattern in (_EN_DIGIT_ROOMS, _EN_BED_ROOMS, _RU_DIGIT_ROOMS, _RU_SHORT_ROOMS):
        out = pattern.sub(lambda m: f"{m.group(1)} bedroom", out)
    return out
