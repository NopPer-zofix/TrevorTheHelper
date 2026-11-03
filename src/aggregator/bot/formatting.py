"""Builds the HTML messages. All user-derived text is escaped here; all wording comes from i18n."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from decimal import Decimal
from html import escape

from aggregator.bot.i18n import Texts
from aggregator.domain.cities import City
from aggregator.domain.models import BestDeal, Listing
from aggregator.search.models import ResultView, SearchOutcome, SourceStatus

PAGE_SIZE = 5
TELEGRAM_MESSAGE_LIMIT = 4096
_SAFETY_MARGIN = 96  # room for tags the length estimate does not see
_TITLE_LENGTHS = (80, 50, 30)

SOURCE_LABELS = {"bazaraki": "Bazaraki", "telegram": "Telegram", "facebook": "Facebook"}


def source_label(name: str) -> str:
    return SOURCE_LABELS.get(name, name.capitalize())


def format_money(amount: Decimal) -> str:
    rounded = amount.quantize(Decimal("0.01"))
    if rounded == rounded.to_integral_value():
        return f"€{int(rounded):,}"
    return f"€{rounded:,.2f}"


def page_count(total: int) -> int:
    return max(1, math.ceil(total / PAGE_SIZE))


def clamp_page(page: int, total: int) -> int:
    return min(max(page, 0), page_count(total) - 1)


def _truncate(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _link(url: str, title: str, title_limit: int) -> str:
    return f'<a href="{escape(url, quote=True)}">{escape(_truncate(title, title_limit))}</a>'


# --- progress -----------------------------------------------------------------------------


def format_progress(
    t: Texts,
    query: str,
    city: City,
    source_names: Sequence[str],
    done: Mapping[str, SourceStatus],
) -> str:
    lines = [t("searching", query=escape(query), city=t.city(city.value))]
    for name in source_names:
        status = done.get(name)
        label = source_label(name)
        if status is None:
            lines.append(t("progress_waiting", source=label))
        elif status.ok:
            lines.append(t("progress_done", source=label, count=status.count))
        else:
            lines.append(t("progress_failed", source=label))
    return "\n".join(lines)


# --- results ------------------------------------------------------------------------------


def _header(t: Texts, outcome: SearchOutcome, view: ResultView) -> list[str]:
    lines = [
        t(
            "header",
            query=escape(outcome.query.original.strip() or outcome.query.normalized),
            city=t.city(outcome.city.value),
        )
    ]
    parts = [
        t("source_unavailable", source=source_label(s.name))
        if not s.ok
        else f"{source_label(s.name)} {view.counts_by_source.get(s.name, 0)}"
        for s in outcome.statuses
    ]
    if parts:
        lines.append(t("found_per_source", total=len(view.listings), parts=" · ".join(parts)))
    failed = outcome.failed_sources
    if failed:
        lines.append(t("partial_note", sources=", ".join(source_label(s.name) for s in failed)))
    return lines


def _stats(t: Texts, view: ResultView) -> list[str]:
    stats = view.stats
    if stats.priced_count == 0:
        return [t("stats_none")]
    title = t("stats_title", sample=stats.sample_size)
    if stats.outliers_removed:
        title += t("stats_outliers", removed=stats.outliers_removed)
    lines = [title]
    if not stats.reliable:
        lines.append(t("stats_unreliable", count=stats.priced_count))
    assert stats.average and stats.median and stats.minimum and stats.maximum
    lines.append(
        t(
            "stats_line",
            average=format_money(stats.average),
            median=format_money(stats.median),
            minimum=format_money(stats.minimum),
            maximum=format_money(stats.maximum),
        )
    )
    if view.unpriced_count:
        lines.append(t("stats_unpriced", count=view.unpriced_count))
    return lines


def _deals(t: Texts, deals: Sequence[BestDeal], title_limit: int) -> list[str]:
    if not deals:
        return []
    lines = [t("deals_title")]
    for index, deal in enumerate(deals, start=1):
        price = deal.listing.price_eur
        lines.append(
            t(
                "deal_line",
                index=index,
                url=escape(deal.listing.url, quote=True),
                title=escape(_truncate(deal.listing.title, title_limit)),
                price=format_money(price) if price is not None else "",
                discount=deal.discount_pct,
            )
        )
    return lines


def _card(t: Texts, number: int, listing: Listing, title_limit: int) -> str:
    price = listing.price_eur
    if price is None:
        price_text = t("card_price_none")
    else:
        price_text = format_money(price)
        if listing.currency and listing.currency.upper() != "EUR" and listing.price_amount:
            price_text += f" ({listing.price_amount:,.0f} {escape(listing.currency.upper())})"
    city_text = t.city(listing.city.value)
    posted = t("card_posted", date=listing.posted_at.strftime("%d.%m.%Y"))
    meta = f"{price_text} · {city_text} · {source_label(listing.source)} · {posted}"
    return f"{number}. {_link(listing.url, listing.title, title_limit)}\n    {meta}"


def format_results(t: Texts, outcome: SearchOutcome, view: ResultView, page: int) -> str:
    """Header + stats + best deals + the cards of `page` (0-based), within Telegram's limit."""
    total = len(view.listings)
    page = clamp_page(page, total)
    start = page * PAGE_SIZE
    chunk = view.listings[start : start + PAGE_SIZE]
    budget = TELEGRAM_MESSAGE_LIMIT - _SAFETY_MARGIN

    def compose(title_limit: int, card_count: int) -> str:
        sections = ["\n".join(_header(t, outcome, view)), "\n".join(_stats(t, view))]
        deals = _deals(t, view.best_deals, title_limit)
        if deals:
            sections.append("\n".join(deals))
        if card_count:
            cards = [
                _card(t, start + i, li, title_limit)
                for i, li in enumerate(chunk[:card_count], start=1)
            ]
            heading = t("page_title", page=page + 1, pages=page_count(total))
            sections.append(heading + "\n" + "\n".join(cards))
        return "\n\n".join(sections)

    # Shorten titles first; if that is still not enough (very long URLs), show fewer cards.
    # Never cut the HTML itself: a half-cut tag makes Telegram reject the whole message.
    for title_limit in _TITLE_LENGTHS:
        text = compose(title_limit, len(chunk))
        if len(text) <= budget:
            return text
    for card_count in range(len(chunk) - 1, -1, -1):
        text = compose(_TITLE_LENGTHS[-1], card_count)
        if len(text) <= budget:
            return text
    return text


def format_empty(t: Texts, outcome: SearchOutcome) -> str:
    """No listings at all: either every source failed, or nothing matched."""
    if outcome.all_failed:
        return t("all_failed")
    lines = [
        t(
            "no_results",
            query=escape(outcome.query.original.strip() or outcome.query.normalized),
            city=t.city(outcome.city.value),
        )
    ]
    failed = outcome.failed_sources
    if failed:
        lines.append(t("partial_note", sources=", ".join(source_label(s.name) for s in failed)))
    return "\n\n".join(lines)
