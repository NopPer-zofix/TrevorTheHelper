"""Neighbourhoods and towns of Cyprus, with the many ways people write them.

Used to find WHERE a listing is, from free text ("Продаю в Гермасойе", "Yermasoyia, Limassol",
"Айя-Напа") and to give Bazaraki's area names one canonical spelling.

Matching is forgiving on purpose:
- case does not matter, "ё" is "е";
- hyphens, dots, apostrophes and dashes count as spaces ("Айя-Напа" = "айя напа");
- doubled letters are collapsed on both sides ("Лимассол" = "Лимасол", "Pissouri" = "Pisouri"),
  so an alias never needs a doubled-letter twin;
- a Russian alias (5+ letters) also matches with up to 3 extra letters, the case ending
  ("в Гермасойе", "из Строволоса"). Shorter aliases must be a whole word, so "тала" never
  matches "талант".

The alias lists are hand-made and best-effort: spellings seen in real posts can be added to the
tuples below. Ambiguous words (a "полис" is also an insurance policy, "пила" a saw) are left out.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from aggregator.domain.cities import City

_SEPARATORS = re.compile(r"[-–—_'’`./,()]+")
_DOUBLED = re.compile(r"([^\W\d_])\1+")
_CYRILLIC = re.compile(r"[а-я]")
_TOURIST_AREA = " tourist area"  # Bazaraki's suffix for the coastal part of a neighbourhood
_SUFFIX_LETTERS = 3
_MIN_STEM_FOR_ENDINGS = 5


def fold_spelling(text: str) -> str:
    """The comparison form: lower case, no "ё", separators as spaces, doubled letters collapsed."""
    folded = text.lower().replace("ё", "е")
    folded = _SEPARATORS.sub(" ", folded)
    folded = _DOUBLED.sub(r"\1", folded)
    return " ".join(folded.split())


@dataclass(frozen=True)
class Area:
    name: str  # canonical English name, as Bazaraki writes it where known
    city: City
    aliases: tuple[str, ...]  # other spellings, Latin and Russian (any case)


def _a(name: str, city: City, aliases: str) -> Area:
    return Area(name, city, tuple(alias.strip() for alias in aliases.split("|") if alias.strip()))


L, N, C, P, F = City.LIMASSOL, City.NICOSIA, City.LARNACA, City.PAPHOS, City.FAMAGUSTA

AREAS: tuple[Area, ...] = (
    # --- Limassol -----------------------------------------------------------------------------
    _a("Germasogeia", L, "yermasoyia|yermasogeia|germasoyia|гермасойя|гермасойа|гермасогия|"
       "гермасогейя|гермасоя|жермасойя|ермасойя"),
    _a("Potamos Germasogeias", L, "potamos germasogeias|potamos tis germasogeias|"
       "потамос гермасойя|потамос гермасойяс"),
    _a("Agios Tychon", L, "agios tychon|agios tychonas|ayios tychonas|agios tihon|agios tichon|"
       "агиос тихонас|айос тихонас|агиос тихон|айос тихон|агиос тихон|тихонас"),
    _a("Mesa Geitonia", L, "mesa geitonia|mesa yitonia|mesa gitonia|mesa gitonia|меса гитония|"
       "меса гейтония|меса гитония|меса гитоня"),
    _a("Neapolis", L, "neapolis|неаполис"),
    _a("Zakaki", L, "zakaki|закаки"),
    _a("Agia Zoni", L, "agia zoni|aya zoni|ayia zoni|agia zonh|агия зони|айя зони|ая зони|"
       "агиа зони"),
    _a("Agios Nicolaos", L, "agios nicolaos|agios nikolaos|ayios nikolaos|агиос николаос|"
       "айос николаос|агиос николас"),
    _a("Agios Athanasios", L, "agios athanasios|ayios athanasios|агиос афанасиос|айос афанасиос|"
       "агиос атанасиос"),
    _a("Agios Ioannis", L, "agios ioannis|ayios ioannis|агиос иоаннис|айос иоаннис"),
    _a("Katholiki", L, "katholiki|католики"),
    _a("Kato Polemidia", L, "kato polemidia|като полемидия|като полемидиа"),
    _a("Pano Polemidia", L, "pano polemidia|пано полемидия"),
    _a("Polemidia", L, "polemidia|полемидия"),
    _a("Erimi", L, "erimi|эрими|ерими"),
    _a("Kolossi", L, "kolossi|колосси"),
    _a("Ypsonas", L, "ypsonas|ipsonas|ипсонас"),
    _a("Mouttagiaka", L, "mouttagiaka|moutagiaka|moutayiaka|мутаякка|мутагиака|мутаяка"),
    _a("Trachoni", L, "trachoni|трахони"),
    _a("Panthea", L, "panthea|пантея"),
    _a("Limassol Marina", L, "limassol marina|marina limassol|лимассол марина|марина лимассол"),
    _a("Amathus", L, "amathus|amathounta|аматус|аматунта"),
    _a("Parekklisia", L, "parekklisia|parekklisha|парекклисия|парекглисия"),
    _a("Pyrgos", L, "pyrgos limassol|pirgos|пиргос"),
    _a("Pissouri", L, "pissouri|писсури"),
    _a("Agia Fyla", L, "agia fyla|aya fyla|агия фила"),
    # --- Nicosia ------------------------------------------------------------------------------
    _a("Strovolos", N, "strovolos|стровелос|стровилос|строволос"),
    _a("Egkomi", N, "egkomi|engomi|enkomi|энгоми|эгкоми|енкоми|энкоми"),
    _a("Lakatamia", N, "lakatamia|lakatameia|лакатамия|лакатамея|лакатамиа"),
    _a("Aglantzia", N, "aglantzia|aglandjia|aglangia|агландзия|агландия|агланджия|агланжия"),
    _a("Latsia", N, "latsia|лациа|лация|лаця"),
    _a("Kaimakli", N, "kaimakli|каймакли"),
    _a("Dasoupoli", N, "dasoupoli|dasoupolis|дасуполи|дасуполис"),
    _a("Makedonitissa", N, "makedonitissa|македонитисса"),
    _a("Tseri", N, "tseri|цери"),
    _a("Pallouriotissa", N, "pallouriotissa|палуриотисса|палурьотисса"),
    _a("Anthoupoli", N, "anthoupoli|антуполи"),
    _a("Acropolis", N, "acropolis nicosia|akropolis|акрополис"),
    _a("Agios Dometios", N, "ayios dometios|agios dometios|агиос дометиос|айос дометиос"),
    _a("Kokkinotrimithia", N, "kokkinotrimithia|коккинотримифия|кокинотримития"),
    # --- Larnaca ------------------------------------------------------------------------------
    _a("Mackenzie", C, "mackenzie|mckenzie|mackenzy|маккензи|макензи|маккензи"),
    _a("Oroklini", C, "oroklini|voroklini|орокли|орокклини|орокини|вороклини"),
    _a("Dhekelia", C, "dhekelia|dekelia|dekeleia|декелия|дикелия|декелея"),
    _a("Livadia", C, "livadia|ливадия|ливадиа"),
    _a("Aradippou", C, "aradippou|арадиппу|арадипу"),
    _a("Faneromeni", C, "faneromeni|фанеромени"),
    _a("Kamares", C, "kamares|камарес"),
    _a("Meneou", C, "meneou|менеу"),
    _a("Perivolia", C, "perivolia|pervolia|перволия|перивелия|перивола"),
    _a("Dromolaxia", C, "dromolaxia|дромолаксия"),
    _a("Finikoudes", C, "finikoudes|phinikoudes|финикудес|финикудес"),
    _a("Pyla", C, "pyla village|pyla larnaca|pyla"),
    # --- Paphos -------------------------------------------------------------------------------
    _a("Kato Paphos", P, "kato paphos|kato pafos|като пафос|като пафо"),
    _a("Peyia", P, "peyia|pegeia|paiia|пейя|пегейя|пеия"),
    _a("Coral Bay", P, "coral bay|корал бэй|корал бей|корал-бей|коралл бэй"),
    _a("Chloraka", P, "chloraka|hloraka|хлорака"),
    _a("Geroskipou", P, "geroskipou|героскипу|героскипоу"),
    _a("Mandria", P, "mandria|мандрия"),
    _a("Kissonerga", P, "kissonerga|кисонерга"),
    _a("Anavargos", P, "anavargos|анаваргос"),
    _a("Polis Chrysochous", P, "polis chrysochous|polis chrysohous|полис хрисохус|полис хрисохоу"),
    _a("Latchi", P, "latchi|lachi|лачи|латчи"),
    _a("Universal", P, "universal paphos|юниверсал пафос|универсал пафос"),
    # --- Famagusta (Ammochostos) --------------------------------------------------------------
    _a("Ayia Napa", F, "ayia napa|agia napa|aya napa|aia napa|айя напа|ая напа|аия напа|"
       "айа напа|агия напа|айия напа|аййя напа"),
    _a("Protaras", F, "protaras|протарас"),
    _a("Paralimni", F, "paralimni|паралимни"),
    _a("Deryneia", F, "deryneia|derynia|дериня|дерения|дерини"),
    _a("Sotira", F, "sotira|сотира"),
    _a("Frenaros", F, "frenaros|френарос"),
    _a("Liopetri", F, "liopetri|лиопетри"),
    _a("Kapparis", F, "kapparis|каппарис|капарис"),
    _a("Pernera", F, "pernera|перенера|пернера"),
    _a("Cape Greco", F, "cape greco|kavo gkreko|cavo greco|мыс греко|кейп греко|каво греко"),
    _a("Xylofagou", F, "xylofagou|ксилофагу|ксилофагоу"),
)  # fmt: skip


_VOWEL_ENDINGS = "аяыиуеоью"
_MIN_STEM_AFTER_VOWEL = 6  # shorter stems ("колос" from "колоси") would match "колосок"


def _alias_pattern(alias: str) -> str:
    folded = fold_spelling(alias)
    stem, ending = folded, ""
    if _CYRILLIC.search(folded) and len(folded) >= _MIN_STEM_FOR_ENDINGS:
        if folded[-1] in _VOWEL_ENDINGS:
            # "гермасойя" -> "в гермасойе / гермасойи / гермасойю": the last vowel changes, so
            # match the stem plus up to three letters, but only for stems long enough to be safe.
            if len(folded) - 1 >= _MIN_STEM_AFTER_VOWEL:
                stem, ending = folded[:-1], rf"\w{{0,{_SUFFIX_LETTERS}}}"
        else:
            ending = rf"\w{{0,{_SUFFIX_LETTERS}}}"  # "строволос" -> "в строволосе"
    body = r"\s+".join(re.escape(word) for word in stem.split())
    return rf"(?<!\w){body}{ending}(?!\w)"


def _compile(area: Area) -> re.Pattern[str]:
    names = sorted(
        {fold_spelling(area.name), *map(fold_spelling, area.aliases)}, key=len, reverse=True
    )
    return re.compile("|".join(_alias_pattern(name) for name in names))


_PATTERNS: tuple[tuple[Area, re.Pattern[str]], ...] = tuple(
    (area, _compile(area)) for area in AREAS
)
_EXACT: dict[str, Area] = {}
for _area in AREAS:
    for _name in (_area.name, *_area.aliases):
        _EXACT.setdefault(fold_spelling(_name), _area)


def detect_area(text: str | None) -> Area | None:
    """The neighbourhood mentioned in `text` (the first one, the longest name on a tie)."""
    if not text:
        return None
    haystack = fold_spelling(text)
    best: tuple[int, int, Area] | None = None
    for area, pattern in _PATTERNS:
        match = pattern.search(haystack)
        if match is None:
            continue
        key = (match.start(), -(match.end() - match.start()))
        if best is None or key < (best[0], best[1]):
            best = (key[0], key[1], area)
    return best[2] if best else None


def canonical_area(name: str | None) -> str | None:
    """Bazaraki's own area text mapped to our canonical name, if it is a known spelling.

    Only whole-name matches count ("Germasogeia Tourist Area" -> "Germasogeia"); a longer text
    that merely mentions an area is left alone, so no detail is lost.
    """
    if not name:
        return None
    folded = fold_spelling(name)
    folded = folded.removesuffix(_TOURIST_AREA)
    area = _EXACT.get(folded)
    return area.name if area else name


def locate(text: str | None, detected_city: City) -> tuple[City, str | None]:
    """The (city, area) of a listing. A named area also tells the city when none was named;
    an area that belongs to a different city than the one named is dropped."""
    area = detect_area(text)
    if area is None:
        return detected_city, None
    if detected_city is City.UNKNOWN:
        return area.city, area.name
    return detected_city, area.name if area.city is detected_city else None
