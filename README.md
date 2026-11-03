# TrevorTheHelper: Cyprus second-hand price aggregator

A Telegram bot. You send it a product name ("iphone 13 128gb", "велосипед горный 26"), and it
replies with the active second-hand listings for that product in Cyprus, price statistics
(average, median, min, max in EUR) and the best deals, all in one message. It searches
[Bazaraki](https://www.bazaraki.com) live and a set of Telegram groups that it indexes in the
background. The bot speaks English and Russian. It is meant as a personal tool and a portfolio
project; it is built so it could become a public service later without a rewrite.

> **Read this before running it: Bazaraki forbids automated access.**
> robots.txt allows `/search/`, but Bazaraki's terms of use (<https://www.bazaraki.com/about/rules/>,
> clauses 4.1 and 5.3.1(f)) prohibit robots, scrapers and automated collection of its content.
> This project fetches Bazaraki search pages anyway, **for private, low-volume use only**
> (see [Known limitations](#known-limitations-and-legal-note)). Do not run it as a public
> service, and do not raise the request limits. To run without Bazaraki, set
> `ENABLED_SOURCES=telegram`.

## What the bot does

- `/start` asks for a language (EN/RU), then a city (Nicosia, Limassol, Larnaca, Paphos,
  Famagusta, All Cyprus). `/city` and `/lang` change them later; `/help` lists the commands.
- Send any product name. One "Searching…" message updates as each source answers, then becomes
  the result: a header with counts per source, price stats, up to 3 best deals (priced at or below
  75% of the median), and listing cards, 5 per page with Prev/Next buttons.
- **Filters** button: min/max price (you type a number), sort (newest, cheapest, best deal), source.
  Filters apply to the results already fetched; nothing is searched again.
- If one source fails, you still get the other's results, with a note about which source was down.

## Prerequisites

- **Docker with Docker Compose** (the easy way), or Python 3.12+ and PostgreSQL 16 with the
  `pg_trgm` extension available (the migration enables it).
- A **Telegram bot token** from [@BotFather](https://t.me/BotFather).
- For Telegram-group search: **Telegram API credentials** and a **spare Telegram account**
  (see below). Skip this if you only want Bazaraki.
- Optional: an **Anthropic API key**. Without it the bot expands queries with a built-in
  rule-based fallback (it works, but finds fewer spelling variants).

## Setup

### 1. Create the bot (BotFather)

1. Open [@BotFather](https://t.me/BotFather) in Telegram and send `/newbot`.
2. Pick a name and a username. BotFather replies with a token like `123456:ABC...`.
3. Put it in `.env` as `BOT_TOKEN` (step 4).

### 2. Get Telegram API credentials (only for Telegram groups)

The indexer reads group messages through a normal user account (Telethon), not through the bot.

1. Log in at <https://my.telegram.org> with the phone number of the **dedicated reader account**.
   Use a separate account, not your main one.
2. Open **API development tools**, create an application, and copy `api_id` and `api_hash`.
3. That account must be a **member of every group** you want indexed. The indexer is read-only:
   it never sends, edits, deletes or joins anything (a test enforces this).

### 3. Find your Telegram user id

Send a message to [@userinfobot](https://t.me/userinfobot) to get your numeric id. Put it in
`ALLOWED_USER_IDS`. **If this is empty, anyone who finds the bot can use it.**

### 4. Configure

```bash
cp .env.example .env        # PowerShell: Copy-Item .env.example .env
```

Fill in at least:

```dotenv
BOT_TOKEN=123456:ABC...
ALLOWED_USER_IDS=111111111
# Only for Telegram groups:
TELEGRAM_API_ID=1234567
TELEGRAM_API_HASH=0123456789abcdef0123456789abcdef
TELEGRAM_GROUPS=baraholka_kipr,https://t.me/some_other_group
```

`.env`, `*.session` and `data/` are gitignored. Never commit them.

### 5. Log the reader account in (once)

This is interactive: it asks for the phone number, the login code and the 2FA password if set.
Run it on your machine, not in Docker. It writes the session file to `./data/`.

```bash
python -m venv .venv
.venv/bin/pip install -e .                  # Windows: .venv\Scripts\pip install -e .
.venv/bin/python -m aggregator.sources.telegram.login   # or: make telegram-login
```

### 6. Start everything

```bash
docker compose up --build        # or: make up
```

This starts four containers: `postgres`, a one-shot `migrate` (applies the Alembic migrations),
`bot`, and `indexer`. Then open your bot in Telegram, send `/start`, and search for something.

Bazaraki-only, with no Telegram account? Set `ENABLED_SOURCES=bazaraki` and start only the bot:
`docker compose up --build bot` (it brings up `postgres` and `migrate` as dependencies).

### Running without Docker

```bash
pip install -e ".[dev]"
# DATABASE_URL in .env must point at your Postgres (default: localhost:5432, user/password/db "aggregator")
alembic upgrade head
aggregator-bot                          # in one terminal
HEALTH_PORT=8081 aggregator-indexer     # in another (PowerShell: $env:HEALTH_PORT=8081; aggregator-indexer)
```

Both processes expose `GET /health` on `HEALTH_PORT` (default 8080); the compose healthchecks use
it. On one host they need different ports, hence `8081` above. In Docker each has its own network.

## Configuration

All settings are environment variables, read from `.env` (see `.env.example`;
the full list is in `src/aggregator/config.py`). The most useful ones:

| Variable | Default | What it does |
|---|---|---|
| `BOT_TOKEN` | – | Bot token from BotFather. The bot exits at startup without it. |
| `ALLOWED_USER_IDS` | empty | Comma-separated Telegram ids allowed to use the bot. **Empty = public.** |
| `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` | – | Credentials from my.telegram.org for the reader account. |
| `TELEGRAM_GROUPS` | empty | Groups to index: usernames or `t.me` links, comma-separated. |
| `TELEGRAM_SESSION_PATH` | `./data/reader.session` | Where the Telethon login session is stored. |
| `TELEGRAM_BACKFILL_DAYS` | `30` | How much history the indexer loads on startup. |
| `ANTHROPIC_API_KEY` | empty | Enables LLM query expansion. Empty = rule-based fallback. |
| `ANTHROPIC_MODEL` | `claude-haiku-5-5` | Model used for query expansion. |
| `DATABASE_URL` | `postgresql+asyncpg://aggregator:aggregator@localhost:5432/aggregator` | Postgres connection. Compose overrides the host to `postgres`. |
| `ENABLED_SOURCES` | `bazaraki,telegram` | Which sources the bot queries, in display order. |
| `ENABLE_FACEBOOK_MARKETPLACE` | `false` | Adds the (unimplemented) Facebook stub. Leave off. |
| `BAZARAKI_CACHE_TTL_SECONDS` | `300` | How long a Bazaraki result is reused for the same query and city. |
| `LISTING_MAX_AGE_DAYS` | `30` | Telegram listings older than this are not shown. |
| `BEST_DEAL_RATIO` | `0.75` | A "best deal" costs at most this fraction of the median. |
| `RELEVANCE_MIN_SCORE` | `0.75` | Listings that match the query worse than this (0–1) are dropped. |
| `RATE_LIMIT_ENABLED` | `false` | Per-user rate limit (`RATE_LIMIT_REQUESTS` per `RATE_LIMIT_WINDOW_SECONDS`, default 5 per 60 s). |
| `LOG_LEVEL`, `LOG_JSON` | `INFO`, `true` | Logging. Set `LOG_JSON=false` for readable local output. |

## How it works

```mermaid
flowchart LR
    User([Telegram user]) <--> Bot["bot process<br/>aiogram handlers"]
    Bot --> Svc["services<br/>users, search, sessions,<br/>rate limit, quota"]
    Svc --> QE["query expansion<br/>LLM or rule-based"]
    Svc --> Orch["search orchestrator<br/>fan-out, timeouts,<br/>relevance, stats"]
    QE <--> DB[(PostgreSQL)]
    Orch --> Baz["Bazaraki source<br/>live HTML fetch + TTL cache"]
    Orch --> TgSrc["Telegram source<br/>full-text + trigram search"]
    TgSrc --> DB
    Baz --> Site[(bazaraki.com)]
    Idx["indexer process<br/>Telethon, read-only"] -->|backfill and live events| DB
    Groups[(Telegram groups)] --> Idx
```

The `bot` and `indexer` processes share only the database.

1. The bot expands your text into a normalized name, English and Russian variants, and
   negative terms ("case", "wanted"). Expansions are cached in Postgres.
2. The orchestrator asks every enabled source at once, each with its own timeout. A source that
   fails or times out is reported and skipped.
3. A relevance filter drops poor matches (so "iPhone 13" doesn't return cases and chargers),
   duplicates are removed, and prices are converted to EUR.
4. Stats use the IQR rule to drop outliers; fewer than 3 priced listings is flagged as
   unreliable, and best deals need at least 5 priced listings.

## Project structure

```text
src/aggregator/
  config.py          settings (pydantic-settings)
  domain/            Listing, ExpandedQuery, Filters, cities, currency, price parsing
  sources/           one package per source; base.py holds the ListingSource interface
    bazaraki/        HTTP client, parser, selectors (kept in one file)
    telegram/        Telethon indexer, message parser, DB-backed source, login script
    facebook/        disabled stub
    registry.py      builds the sources enabled by config
  query/             query expansion: LLM, rule-based fallback, cache
  search/            orchestrator, relevance filter, filters and sorting
  analytics/         price stats, outlier removal, best deals
  services/          what the bot calls: users, search, sessions, rate limit, quota
  bot/               aiogram handlers, keyboards, formatting, i18n (en/ru), entrypoint
  db/                SQLAlchemy models, repositories, Alembic migrations
  cache.py           TTL cache behind an interface (in memory now, Redis-ready)
tests/               pytest; no live network calls
docs/                spec (BUILD_PROMPT.md), progress notes, Bazaraki research
```

## Development

```bash
pip install -e ".[dev]"
ruff check . && ruff format --check . && mypy && pytest     # same as: make check
```

Tests that need Postgres (`tests/test_repositories.py`, `tests/test_user_store.py`) are skipped
unless `TEST_DATABASE_URL` is set. **They drop all tables in that database**, so point it at a
throwaway one. CI does this with a Postgres service container.

### Adding a new source

1. Create `src/aggregator/sources/<name>/source.py` with a class that has a `name` string and
   `async def search(self, query: ExpandedQuery, city: City | None, filters: Filters) -> list[Listing]`
   (the `ListingSource` protocol in `sources/base.py`). Raise `SourceError` on failure.
2. Return `Listing` objects with a unique `external_id` per source. Put the price in
   `price_amount` and `currency`; leave it `None` if unknown.
3. Add a branch for the name in `build_registry()` in `sources/registry.py`.
4. Add the name to `ENABLED_SOURCES`, and add a label in `SOURCE_LABELS` in `bot/formatting.py`.
5. Test it with saved fixtures; see `tests/test_bazaraki_parser.py`. The orchestrator, relevance
   filter, stats, filters and the bot need no changes.

## Known limitations and legal note

- **Bazaraki terms of use.** Their terms prohibit automated access (see the box at the top).
  robots.txt does not disallow `/search/`, but that doesn't override the terms. The client only
  requests `/search/` HTML pages, never the disallowed `/api` or `attrs_*` URLs. It spaces
  requests at least `BAZARAKI_MIN_REQUEST_INTERVAL_SECONDS` apart (1 s), caches results, sends an
  honest User-Agent, retries only temporary errors, and does not retry or work around a 403 or
  a CAPTCHA. Treat the project as private use only. Details in `docs/research/bazaraki.md`.
- **Telegram groups.** Group messages are stored in your own database. Use a dedicated account
  and only groups you are a member of; Telegram's API terms and each group's rules still apply.
- **Bazaraki dates are approximate.** The site only gives relative dates ("3 days ago"), so the
  bot shows them as `~dd.mm.yyyy`.
- **Bazaraki markup can change.** The parser reads data embedded in the page. If that disappears,
  the source fails loudly ("source unavailable") instead of returning nothing silently.
- **Relevance is heuristic.** "iPhone 13 Pro Max" can still match a search for "iphone 13".
  A multi-item post yields only its first price. A price with no currency is read as EUR.
- **Filters and sessions.** Price filters are in euros, and listings without a price are hidden
  while a price bound is set. Results are kept in memory for `RESULT_SESSION_TTL_SECONDS` (1 hour),
  so a restart expires them. Old result messages stay clickable but act on your latest search.
- **City detection for Telegram posts** is a lookup table. A post with no recognisable city is
  labelled "unknown" and shown only under "All Cyprus".
- **Polling only.** Webhook mode (`BOT_MODE=webhook`) is a documented stub in `bot/runner.py`.
- **Facebook Marketplace is not implemented.** See below.
- **Verification status.** The test suite uses fakes and saved fixtures. The full stack has not
  yet been run end to end against real Telegram, Bazaraki and Postgres, and the Anthropic query
  expansion has only been tested with a fake client. Expect to fix small things on first run.

### Why Facebook Marketplace is hard

There is no public API for Marketplace listings. Viewing them requires a logged-in account.
Automated access violates Meta's terms and gets accounts restricted or banned, and the site
actively detects automation. `FacebookMarketplaceSource` exists only as a stub that raises
`NotImplementedError`, behind `ENABLE_FACEBOOK_MARKETPLACE`. Approaches worth trying later:
an official data partnership, a user-supplied export or share-link flow, or a manual-assist
browser extension where the user browses and the tool only reads what they already see.
Bypassing the login wall or anti-bot checks is not an option.

## Roadmap

- **Facebook Marketplace** source (see above).
- **Saved searches and alerts:** notify when a new listing matches or drops below a price.
- **Cross-platform dedupe** of the same item posted on several sites.
- **Plans and payments:** `users.plan` and `check_quota()` are the hooks; today they always allow.
- **Scaling out:** Redis behind the existing `Cache` interface, webhook mode, a task queue.
- **More sources.**
