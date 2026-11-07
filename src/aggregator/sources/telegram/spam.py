"""Recognise spam posts in the Telegram groups, so they never become "listings".

What the groups really contain (seen in 8,700 stored messages): about a third is not for sale
anything: Chinese "earn money" posts, recruitment bots ("Ищу людей в команду... заработок 150-200 в
неделю... пиши @user"), often written with look-alike letters to dodge filters ("Obучение"), and
posts that are only a link or a row of emoji digits.

Each rule below is independent and deliberately narrow: wrongly dropping a real listing is worse
than letting a little spam through. A reason string is returned (for the log); None means "fine".
"""

from __future__ import annotations

import re

CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯]")
URL = re.compile(r"(?:https?://|www\.|t\.me/)\S+", re.IGNORECASE)
LETTER_RUN = re.compile(r"[^\W\d_]+")
CYRILLIC_LETTER = re.compile(r"[а-яёіїєґ]", re.IGNORECASE)
LATIN_LETTER = re.compile(r"[a-z]", re.IGNORECASE)

MIN_CJK_CHARS = 3
MIN_MIXED_SCRIPT_WORDS = 3
MIN_LETTERS = 3

# "Job offer / easy money" vocabulary (Russian and Ukrainian). A group is hit at most once.
_GROUPS: dict[str, re.Pattern[str]] = {
    "earn": re.compile(
        r"заработ|зарабат|заробіт|заробит|доход|дохід|выручк|виручк|прибыл|прибут|навар"
    ),
    "period": re.compile(
        r"в день|в неделю|в сутки|за смену|за день|за зміну|щодня|щотижня|в тиждень|ежедневн"
    ),
    "pay": re.compile(r"оплат|выплат|виплат|зарплат|зарплатн"),
    "uah": re.compile(r"грн|₴|гривн|\buah\b"),
    "noexp": re.compile(
        r"без опыта|без досвіду|опыт не требуется|опыта не нужно|опыт не нужен|обучени\w* бесплатн"
        r"|бесплатн\w* обучени|навчання|обучим|навчимо|научим|научу"
    ),
    "work": re.compile(
        r"(?<!\w)(?:работ[аыуе]|работать|робот[аиуе]|вакансі|вакансии|подработк\w*|підробіт\w*"
        r"|требуются|потрібн\w*|ищем|шукаємо|ищу людей|набор)(?!\w)"
    ),
    "remote": re.compile(r"удал[её]нн|дистанц|віддален|из дома|з дому"),
}
# "от 150$ за смену", "2000 грн в день", "150-200$ в неделю"
_MONEY_PER_PERIOD = re.compile(
    r"\d[\d\s\-–]*\s*(?:\$|usd|€|eur|евро|грн|₴|💵|💰|долл\w*)\s*(?:/|за|в)\s*"
    r"(?:смен|день|дн|неделю|сутки|час|зміну|тиждень)"
    r"|(?:\$|usd|€|евро|грн|₴|💵|💰)\s*\d[\d\s\-–]*\s*(?:/|за|в)\s*(?:смен|день|неделю|сутки)"
    r"|\d[\d\s\-–]*\s*(?:\$|usd|€|евро|грн|₴|💵|💰)?\s*в\s+(?:неделю|день|сутки)"
)
# A job vacancy is never a thing for sale: "вакансия" plus any other job word is enough.
_VACANCY = re.compile(r"ваканс")
# Telegram handle, "write me" calls, or a phone number
_CONTACT = re.compile(
    r"@\w{4,}|t\.me/(?!m/)|(?<!\w)tg\s*:|(?<!\w)тг\s*:|пиши(?:те)?(?!\w)|писати|звертайтесь"
    r"|обращайтесь|\+\d[\d\s\-()]{8,}"
)


def _mixed_script_words(text: str) -> int:
    """Words that mix Cyrillic and Latin letters ("Obучение"): look-alike obfuscation."""
    count = 0
    for run in LETTER_RUN.findall(text):
        if CYRILLIC_LETTER.search(run) and LATIN_LETTER.search(run):
            count += 1
    return count


def _job_offer(folded: str, with_links: str) -> bool:
    hits = {name for name, pattern in _GROUPS.items() if pattern.search(folded)}
    has_contact = _CONTACT.search(with_links) is not None
    per_period = _MONEY_PER_PERIOD.search(folded) is not None
    if len(hits) >= 4:
        return True
    if _VACANCY.search(folded) and len(hits) >= 2:
        return True
    if has_contact and len(hits) >= 3:
        return True
    return has_contact and per_period and len(hits) >= 2


def spam_reason(text: str | None) -> str | None:
    """Why `text` is spam ("cjk", "no_text", "lookalike_letters", "job_offer"), or None."""
    if not text or not text.strip():
        return None  # an empty message is handled elsewhere (skipped_empty)
    if len(CJK.findall(text)) >= MIN_CJK_CHARS:
        return "cjk"
    without_links = URL.sub(" ", text)
    if sum(ch.isalpha() for ch in without_links) < MIN_LETTERS:
        return "no_text"  # only a link, or a row of emoji / digits
    if _mixed_script_words(without_links) >= MIN_MIXED_SCRIPT_WORDS:
        return "lookalike_letters"
    folded = without_links.casefold().replace("ё", "е")
    if _job_offer(folded, text.casefold().replace("ё", "е")):
        return "job_offer"
    return None
