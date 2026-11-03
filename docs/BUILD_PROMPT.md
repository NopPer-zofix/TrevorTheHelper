# Build prompt: Second-Hand Price Aggregator Telegram Bot (Cyprus)

## 1. Role and goal

You are a senior Python engineer. Build **a Telegram bot that aggregates second-hand listings from several platforms in Cyprus**, so a user can type a product name and get back all active listings, price statistics and the best deals in one message.

This is first a **private portfolio project** that runs on my local machine (Docker Compose). It must be **architected so it can later become a public free or monetized service without a rewrite**. Code quality, tests and documentation matter, because the repo will be reviewed by recruiters and engineers.

## 2. Scope by phase

**Phase 1 (build now, MVP)**

- Sources: **Bazaraki** and **Telegram groups** (I will give you the list).
- Bot flow: city selection, product search, results with stats, best deals, listing cards, filters.
- Languages: bot interface and search queries in **English and Russian**.

**Phase 2 (design for it now, don't implement)**

- **Facebook Marketplace** source. Create a `FacebookMarketplaceSource` stub that is disabled by a feature flag and raises `NotImplementedError`. Document in the README why it is hard (no public API, login wall, ban risk) and which approaches could be tried.

**Phase 3 (leave extension points only)**

- Saved searches and alerts, cross-platform dedupe, user plans and payments. Don't build these, but the data model and code structure must not block them (see §7).

**Out of scope:** Greek language, photos and media previews, favorites and search history, a web UI.

## 3. Tech stack (fixed)

- Python 3.12, fully async (`asyncio`)
- **aiogram 3** for the bot
- **Telethon** for reading Telegram groups through a user account
- **httpx** plus **selectolax** or **BeautifulSoup** for Bazaraki. Use **Playwright** only if plain HTTP can't get the data.
- **PostgreSQL** with **SQLAlchemy 2.0 (async)** and **Alembic** migrations
- **Anthropic Python SDK** for LLM query expansion (§5)
- **pydantic-settings** for config, **structlog** for logging
- **pytest**, **pytest-asyncio**, **respx**, **ruff**, **mypy** (strict on core modules)
- **Docker Compose**: services `bot`, `indexer`, `postgres`. A Makefile for common tasks. GitHub Actions CI running lint, type-check and tests.

## 4. Architecture

Use a clean, modular layout, for example:

```
src/aggregator/
  config.py
  domain/            # Listing, SearchQuery, ExpandedQuery, Stats, Filters (pydantic models)
  sources/
    base.py          # ListingSource protocol
    bazaraki/        # live fetch + parser (selectors isolated in one file)
    telegram/        # Telethon indexer + message parser
    facebook/        # disabled stub (phase 2)
    registry.py      # sources enabled via config
  query/             # LLM query expansion + cache
  search/            # orchestrator: fan-out to sources, relevance filter, merge
  analytics/         # price stats, outlier filtering, best-deal detection
  bot/               # aiogram handlers, keyboards, formatting, i18n (en/ru)
  db/                # models, repositories, migrations
  cache.py           # TTL cache behind an interface (in-memory now, Redis-ready)
tests/
```

Rules:

- Every source implements one interface: `async def search(query: ExpandedQuery, city: City | None, filters: Filters) -> list[Listing]`. The orchestrator must work with any number of sources and tolerate one failing (return partial results and tell the user which source failed).
- Two processes: `bot` (handles users) and `indexer` (Telethon, runs continuously). They share only the database.
- No business logic in bot handlers. Handlers call a service layer.

## 5. Features in detail

### 5.1 City selection

- Fixed list: **Nicosia, Limassol, Larnaca, Paphos, Famagusta, All Cyprus** (inline keyboard).
- Remember the choice per user and let them change it with `/city`.
- Bazaraki: map to its location filter. Telegram posts: detect the city from the text (English, Russian and common transliterations or spellings) with a lookup table. If no city is detectable, mark the listing `city=unknown` and **include it in "All Cyprus"** results but clearly label it.

### 5.2 Query expansion (LLM)

- Input: free-text product name, for example `iphone 13 128gb`, `велосипед горный 26`.
- Use the Anthropic API with structured (JSON-schema) output to produce an `ExpandedQuery`: normalized product name, brand, model, key specs, a list of **search-term variants in English and Russian** (including common spellings and abbreviations), **negative terms** (accessories, "wanted" posts, cases and so on), and a category hint.
- Cache expansions by normalized input (DB table). Add a hard timeout and a **rule-based fallback** (tokenize, strip stop words) if the API fails or the key is missing, so the bot still works.
- The model name must be configurable by env var (`ANTHROPIC_MODEL`), not hard-coded.

### 5.3 Searching and "active" listings

- **Bazaraki:** fetch live per request with a polite rate limit, a clear User-Agent, retries with backoff, and a **short TTL cache (default 5 min)** per (query, city). Before writing the parser, **inspect the real site** (HTML and any internal JSON endpoints it loads) and check its robots.txt and terms. Isolate all selectors in one module and keep saved HTML fixtures for tests.
- **Telegram groups:** the `indexer` uses Telethon to (a) backfill recent history (default 30 days) and (b) listen for new, edited and deleted messages in the configured groups. Each message is parsed into a `Listing` (title or text, price and currency, city, link to the message, posted-at). A listing is **active** if it is newer than `LISTING_MAX_AGE_DAYS` (default 30), hasn't been deleted, and doesn't contain sold markers (`sold`, `продано`, `продан`, ...). Skip "wanted" posts (`куплю`, `looking for`, `wtb`). Telegram search runs against the database, not live. Use Postgres full-text search plus trigram similarity.
- The Telethon session uses a **dedicated Telegram account**, **read-only** (never sends messages). The session file and credentials are never committed.
- **Relevance filter** after fetching: score each listing against the expanded query (variants, negative terms) and drop poor matches, so "iPhone 13" doesn't return cases and chargers.

### 5.4 Results message

For each search, send:

1. **Summary header:** query, city, number of listings found per source, and price stats (**average, median, min, max** in EUR). Compute stats after IQR outlier removal and show the sample size. Skip listings without a price. If fewer than 3 priced listings exist, say stats are unreliable.
2. **Best deals:** listings priced at or below `BEST_DEAL_RATIO` (default 0.75) of the median, only when at least 5 priced listings exist. Show the top 3 with the discount percentage.
3. **Listing cards**, paginated (5 per page) with Prev/Next inline buttons. Each card: title, price, city, source, posted date, and a link to the original listing. No photos.

- Edit a single "Searching..." message with progress while sources respond, instead of sending several messages.
- Respect Telegram message length limits and escape the formatting correctly (use HTML parse mode).

### 5.5 Filters

After results are shown, an inline **Filters** button lets the user set: **min and max price**, **sort order** (cheapest, newest, best deal) and **source** (all, Bazaraki, Telegram). Filters apply to the already-fetched result set without re-scraping. Keep them in the user's session state and show a "Reset filters" button.

### 5.6 Bot UX

- `/start` shows language choice (EN or RU), then city selection. Then the user simply sends a product name to search.
- Commands: `/start`, `/city`, `/lang`, `/help`.
- All user-facing strings go through an i18n layer (`en`, `ru`) with no hard-coded strings in handlers.
- Friendly handling of: empty results (suggest broader terms), a failing source, rate limits, and invalid input.

## 6. Data model (minimum)

- `users` (telegram_id, language, city, created_at, `plan` default `"private"`, is_allowed)
- `listings` (id, source, external_id, url, title, description, price_amount, currency, city, posted_at, last_seen_at, is_active, raw jsonb) with a unique constraint on (source, external_id)
- `query_expansions` (normalized_input, payload jsonb, created_at)
- `search_log` (user_id, query, city, result_count, duration_ms, created_at)

Normalize all prices to EUR for stats (store the original currency too). Treat "negotiable" or missing prices as null.

## 7. Built-in scalability hooks (cheap now, valuable later)

- **Private mode:** `ALLOWED_USER_IDS` env allowlist. Non-listed users get a polite refusal. Switching to public means removing the allowlist.
- **Per-user rate limiting** middleware (configurable, off by default for private mode).
- `users.plan` field plus a `check_quota(user)` function that currently always allows. This is the monetization seam.
- Cache and source registry behind interfaces so Redis, a task queue or more sources can be added without touching handlers.
- Run the bot with long polling now, but keep the webhook setup isolated so it is easy to switch.
- Structured logs and a `/health` check for the processes.

## 8. Non-functional requirements

- Secrets only via env (`.env.example` provided, `.env` gitignored): `BOT_TOKEN`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `ANTHROPIC_API_KEY`, `DATABASE_URL`, `TELEGRAM_GROUPS`, etc.
- Per-source timeouts, retries with backoff, and graceful degradation.
- Be a good citizen toward the sites: rate limits, caching, no login-wall circumvention, no CAPTCHA bypass.
- Tests: unit tests for the query fallback, price and city parsing, stats and best-deal logic, and the relevance filter; parser tests against saved fixtures; an integration test of the orchestrator with fake sources; a handler test for the main bot flow. No live network calls in tests.
- README with: overview, architecture diagram (Mermaid), setup (BotFather, Telegram API credentials, Docker Compose), configuration table, how to add a new source, known limitations (including a short legal and ToS note), and the roadmap.

## 9. Working agreement

1. Start with a short plan and the repo skeleton, then work milestone by milestone: (1) skeleton, config, DB and CI; (2) domain models, analytics and tests; (3) Bazaraki source; (4) Telethon indexer and parser; (5) query expansion; (6) orchestrator and bot UX; (7) i18n, filters and polish; (8) README.
2. Commit after each milestone with a clear message.
3. When you need to look at a real page or API, do it instead of guessing, and record what you found.
4. If a requirement is ambiguous or something I must supply is missing, ask me. Don't invent it.
5. Finish each milestone with a short note: what works, what is untested, what is next.

## 10. Inputs I will provide

- Telegram bot token (from BotFather)
- Telegram `api_id` and `api_hash` for the dedicated reader account
- The list of Telegram groups to index (links or usernames)
- Anthropic API key
- Optionally, the Bazaraki categories I care about most

## 11. Acceptance criteria

- `docker compose up` starts bot, indexer and database from a clean checkout after filling in `.env`.
- Sending "iphone 13" in Limassol returns, within ~15 seconds, a message with per-source counts, average, median, min and max price, up to 3 best deals, and paginated listing cards with working links.
- Searching in Russian ("велосипед") works the same way.
- Killing one source does not break the search. The user sees partial results and a note.
- `make lint test` passes, and CI is green.
- Enabling Facebook Marketplace later means implementing one class and flipping a config flag.
