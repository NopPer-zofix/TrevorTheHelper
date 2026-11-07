"""Builds the HTML messages. All user-derived text is escaped here; all wording comes from i18n."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from decimal import Decimal
from html import escape

from aggregator.bot.i18n import Texts
from aggregator.domain.cities import City
from aggregator.domain.models import BestDeal, Filters, Listing, SortOrder
from aggregator.search.models import ResultView, SearchOutcome, SourceStatus

PAGE_SIZE = 5
TELEGRAM_MESSAGE_LIMIT = 4096
_SAFETY_MARGIN = 96  # room for tags the length estimate does not see
_TITLE_LENGTHS = (80, 50, 30)

# Bazaraki only exposes relative dates ("3 days ago"), so its posted-at is an estimate.
APPROXIMATE_DATE_SOURCES = frozenset({"bazaraki"})

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


def _header(
    t: Texts, outcome: SearchOutcome, view: ResultView, filters: Filters | None = None
) -> list[str]:
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
    if filters is not None and not filters.is_default:
        lines.append(
            t(
                "filters_active",
                summary=format_filters_summary(t, filters),
                shown=len(view.listings),
                total=len(outcome.listings),
            )
        )
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


def _unusual_note(t: Texts, view: ResultView, filters: Filters | None) -> list[str]:
    """Tells the user what the price-case split did, so hidden listings never go unnoticed."""
    unusual = view.unusual
    if unusual.mixed:
        return [t("unusual_mixed")]
    if filters is not None and filters.show_unusual_prices:
        return [t("unusual_shown")] if view.unusual_keys else []
    if not unusual.count:
        return []
    details: list[str] = []
    if unusual.low_count and unusual.low_below is not None:
        details.append(t("unusual_low", price=format_money(unusual.low_below)))
    if unusual.high_count and unusual.high_above is not None:
        details.append(t("unusual_high", price=format_money(unusual.high_above)))
    return [t("unusual_hidden", count=unusual.count, detail=" · ".join(details))]


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


def _card(
    t: Texts, number: int, listing: Listing, title_limit: int, *, unusual: bool = False
) -> str:
    price = listing.price_eur
    if price is None:
        price_text = t("card_price_none")
    else:
        price_text = format_money(price)
        if listing.currency and listing.currency.upper() != "EUR" and listing.price_amount:
            price_text += f" ({listing.price_amount:,.0f} {escape(listing.currency.upper())})"
        if unusual:
            price_text = f"⚠️ {price_text}"
    city_text = t.city(listing.city.value)
    approx = "~" if listing.source in APPROXIMATE_DATE_SOURCES else ""
    posted = t("card_posted", date=approx + listing.posted_at.strftime("%d.%m.%Y"))
    meta = f"{price_text} · {city_text} · {source_label(listing.source)} · {posted}"
    return f"{number}. {_link(listing.url, listing.title, title_limit)}\n    {meta}"


def format_results(
    t: Texts,
    outcome: SearchOutcome,
    view: ResultView,
    page: int,
    filters: Filters | None = None,
    show_deals: bool = True,
) -> str:
    """Header + stats + best deals + the cards of `page` (0-based), within Telegram's limit."""
    total = len(view.listings)
    page = clamp_page(page, total)
    start = page * PAGE_SIZE
    chunk = view.listings[start : start + PAGE_SIZE]
    budget = TELEGRAM_MESSAGE_LIMIT - _SAFETY_MARGIN

    def compose(title_limit: int, card_count: int) -> str:
        stats_block = [*_stats(t, view), *_unusual_note(t, view, filters)]
        sections = ["\n".join(_header(t, outcome, view, filters)), "\n".join(stats_block)]
        deals = _deals(t, view.best_deals, title_limit) if show_deals else []
        if deals:
            sections.append("\n".join(deals))
        if card_count:
            cards = [
                _card(t, start + i, li, title_limit, unusual=li.key in view.unusual_keys)
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


# --- filters ------------------------------------------------------------------------------


def format_price_filter(t: Texts, filters: Filters) -> str:
    low, high = filters.min_price, filters.max_price
    if low is not None and high is not None:
        return t("price_range", low=format_money(low), high=format_money(high))
    if low is not None:
        return t("price_from", low=format_money(low))
    if high is not None:
        return t("price_upto", high=format_money(high))
    return t("price_any")


def format_filters_summary(t: Texts, filters: Filters) -> str:
    """Only the non-default parts, e.g. "from €100 · Cheapest · Bazaraki"."""
    parts: list[str] = []
    if filters.min_price is not None or filters.max_price is not None:
        parts.append(format_price_filter(t, filters))
    if filters.sort is not SortOrder.NEWEST:
        parts.append(t(f"sort.{filters.sort.value}"))
    if filters.source is not None:
        parts.append(source_label(filters.source))
    if filters.show_unusual_prices:
        parts.append(t("summary_unusual"))
    return " · ".join(parts)


def format_filters_menu(
    t: Texts, outcome: SearchOutcome, view: ResultView, filters: Filters
) -> str:
    source = source_label(filters.source) if filters.source else t("source.all")
    return "\n".join(
        [
            t("filters_title"),
            "",
            t("filter_price", value=format_price_filter(t, filters)),
            t("filter_sort", value=t(f"sort.{filters.sort.value}")),
            t("filter_source", value=source),
            t(
                "filter_unusual",
                value=t("unusual.shown" if filters.show_unusual_prices else "unusual.hidden"),
            ),
            "",
            t("filters_matching", shown=len(view.listings), total=len(outcome.listings)),
        ]
    )


def format_no_match(t: Texts, outcome: SearchOutcome, filters: Filters) -> str:
    """Results exist, but the user's filters exclude all of them."""
    return "\n\n".join(
        [
            t("no_match_filters", total=len(outcome.listings)),
            t(
                "filters_active",
                summary=format_filters_summary(t, filters),
                shown=0,
                total=len(outcome.listings),
            ),
        ]
    )
