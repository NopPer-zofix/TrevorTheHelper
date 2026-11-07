"""Turn a raw Telegram group message into structured listing fields (pure, no I/O)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from aggregator.domain.areas import locate
from aggregator.domain.cities import City, detect_city
from aggregator.domain.pricing import ExtractedPrice, extract_price
from aggregator.sources.telegram.spam import spam_reason

MAX_TITLE_LENGTH = 120
WANTED_WINDOW = 100  # "wanted" markers only count near the start of the post

# Deliberately does not match "продаю" / "продается" / "продам" (those are sale offers).
_SOLD = re.compile(
    r"(?<!\w)(?:sold|продано|продан[аоы]?|не\s?актуальн\w*)(?!\w)",
    re.IGNORECASE,
)
_WANTED = re.compile(
    r"(?<!\w)(?:куплю|ищу|wtb|looking\s+for|want\s+to\s+buy|wanted)(?!\w)",
    re.IGNORECASE,
)
_HASHTAG = re.compile(r"#\w+")
_SPACES = re.compile(r"[^\S\n]+")  # horizontal whitespace only
_INVISIBLE = {"️", "‍", "​", "﻿"}  # variation selector, ZWJ, ZWSP, BOM


@dataclass(frozen=True)
class ParsedMessage:
    title: str
    description: str | None
    price: ExtractedPrice | None
    city: City
    is_sold: bool
    is_wanted: bool
    area: str | None = None  # neighbourhood named in the text (not stored: re-derived on read)
    spam: str | None = None  # why the post is spam (see spam.py), or None


def _strip_decorations(line: str) -> str:
    """Drop hashtags, emoji and pictographs; keep currency symbols and letters/digits."""
    line = _HASHTAG.sub(" ", line)
    kept = [
        ch
        for ch in line
        if ch not in _INVISIBLE and unicodedata.category(ch) not in {"So", "Sk", "Cs", "Co", "Cn"}
    ]
    return _SPACES.sub(" ", "".join(kept)).strip(" \t-–—•·*_|:;,.")


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    if " " in cut[limit // 2 :]:
        cut = cut.rsplit(" ", 1)[0]  # prefer a word boundary when one is reasonably close
    return cut.rstrip(" ,.;:-") + "…"


def parse_message(text: str) -> ParsedMessage:
    """Parse one message. Never raises; an empty message yields an empty title."""
    text = text or ""
    lines = text.splitlines()

    title_index: int | None = None
    title_full = ""
    for index, line in enumerate(lines):
        cleaned = _strip_decorations(line)
        if any(ch.isalnum() for ch in cleaned):
            title_index, title_full = index, cleaned
            break

    title = _truncate(title_full, MAX_TITLE_LENGTH)
    description: str | None = None
    if title_index is not None:
        rest = [ln.strip() for ln in lines[title_index + 1 :]]
        body = "\n".join(rest).strip()
        if title != title_full:
            body = f"{title_full}\n{body}".strip()  # keep the part cut from the title searchable
        description = body or None

    city, area = locate(text, detect_city(text))
    return ParsedMessage(
        title=title,
        description=description,
        price=extract_price(text),
        city=city,
        area=area,
        spam=spam_reason(text),
        is_sold=_SOLD.search(text) is not None,
        is_wanted=_WANTED.search(text[:WANTED_WINDOW]) is not None,
    )
