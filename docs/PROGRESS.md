# Progress and resume guide

Spec: `docs/BUILD_PROMPT.md` (milestones in §9). Last updated: 2026-11-03 (milestone 7).

## Resume in 30 seconds

```powershell
cd D:\Projects\TrevorTheHelper
.venv\Scripts\ruff check . ; .venv\Scripts\ruff format --check . ; .venv\Scripts\mypy ; .venv\Scripts\pytest -q
git log --oneline          # milestone commits
```

Then tell Claude: "read docs/PROGRESS.md and continue with the next step".
(`.venv` is local and gitignored; recreate with `python -m venv .venv` then
`.venv\Scripts\python -m pip install -e ".[dev]"`.)

## Status

| # | Milestone | State |
|---|---|---|
| 1 | Skeleton, config, DB schema + Alembic, Docker Compose, Makefile, CI | Done (committed) |
| 2 | Domain models, city detection, EUR conversion, IQR stats, best deals | Done (committed) |
| 3 | Bazaraki source: parser, polite client, cache, pagination | Done (committed) |
| 4 | Telethon indexer + message parser + DB search | Done (committed `10564ac`); DB tests unverified until CI runs |
| 5 | Query expansion (Anthropic + rule-based fallback + DB cache) | Done (see below); `DbExpansionStore` SQL unverified until CI |
| 6 | Search orchestrator, relevance filter, bot flow, service layer | Done (see below); never run against real Telegram/Bazaraki/DB yet |
| 7 | Filters UI (min/max price, sort, source, reset) + polish | Done (see below) |
| 8 | README (Mermaid diagram, setup, config table, ToS note, roadmap) | Not started |

### Milestone 7: status

Local gate green (343 passed, 13 skipped = CI-only DB tests). Next up: milestone 8 (README).

What exists:
- `services/filters.py` (pure, unit-tested): `parse_price_input` (strict: the whole message must be
  a number, optional euro marker; `0` clears the bound; anything else -> None), `set_price_bound`
  (bounds can never cross -> `FilterError("range")`), `set_sort`, `set_source` (only enabled
  sources accepted).
- Results screen keyboard: pager + **Filters** (+ **Reset filters** when any are active). Filters
  menu (`f:menu`): sort row, source row (All + enabled sources, `✓` on the active one), Min/Max
  price buttons (show the current value), Reset, Back. Callback data `f:menu|back|reset|reset:menu|
  sort:<order>|src:<name|all>|price:<min|max>`. Any filter change returns to page 1; stats and
  best deals are recomputed for the filtered subset; nothing is re-fetched (a test asserts this).
- Price entry is stateless-ish: `SearchSession.pending_price` + `anchor_message_id`. The
  `awaiting_price` handler filter claims a message only if it is a bare number while a price is
  pending; anything else (a new product name) falls through to a normal search, which replaces the
  session. The typed price edits the filters message in place.
- Filters that exclude every listing show "No listings match your filters" with Filters/Reset still
  reachable; an active-filters line (`Filters: from €100 · Cheapest — showing 5 of 8`) is shown in
  the results header.
- Polish: non-text messages get a friendly reply; Bazaraki posted dates are shown as `~dd.mm.yyyy`
  (relative dates only); expired/forged filter callbacks are harmless.
- Tests: `test_filters_service.py`, `test_bot_filters.py` (14 flow tests via the real dispatcher).
  A mutation check showed that "pending price is cleared once accepted" was untested; a test was
  added for it.

Known limitations (candidates for the README):
- Old result messages stay clickable but act on the user's *latest* search session.
- Sessions are in memory: a bot restart or the TTL expires them ("results have expired").
- Only euro price filters; listings without a price are excluded whenever a price bound is set.

### Milestone 6: status

Local gate green (302 passed, 13 skipped = CI-only DB tests).

Scope note: i18n (en/ru catalogs) and Prev/Next pagination were built here instead of in 7,
because the results message and every handler needed them.

What exists:
- `search/relevance.py`: `RelevanceScorer` / `filter_relevant`. Token coverage over `normalized` +
  `variants` (digits exact, prefix-stemming for words, letters/digits split so `iphone13` ==
  `iphone 13`), spec tokens weigh 0.25, description-only matches x0.85, threshold
  `RELEVANCE_MIN_SCORE` (0.75). `negative_terms` match the title only and are cancelled when the
  title shows a bundle ("with charger", "+ case", "incl"). Known limits: "iPhone 13 Pro Max"
  passes for "iphone 13"; a wrong storage size is not penalised beyond the missing spec.
- `search/orchestrator.py`: concurrent fan-out, per-source timeout, any exception -> a failed
  `SourceStatus` (partial results), city scoping via `city_matches`, per-source relevance filter,
  dedupe by (source, external_id), progress callback per source. Sources always get default
  `Filters()`; user filters are applied afterwards (`search/filters.py`: `apply_filters`,
  `sort_listings`, `build_view` -> stats + best deals for the filtered subset).
- `sources/registry.py` (`build_registry`, ordered by `ENABLED_SOURCES`, closes the Bazaraki
  client) and `sources/facebook/source.py` (stub, only added with `ENABLE_FACEBOOK_MARKETPLACE`).
- `services/`: `UserService` (+ `DbUserStore`, `InMemoryUserStore`), `check_quota` (monetization
  seam), `SlidingWindowRateLimiter`, `SessionStore` (last result set per user, in the `Cache`
  interface, TTL `RESULT_SESSION_TTL_SECONDS`), `SearchService` (validate -> expand ->
  orchestrate -> `search_log`; `view(outcome, filters)`).
- `bot/`: `i18n.py` (en/ru, parity enforced by a test), `formatting.py` (HTML, escaping, 4096
  guard that shortens titles then drops cards, never cuts markup), `keyboards.py`
  (`lang:`/`city:`/`pg:` callbacks), `handlers.py` (`build_router()` factory), `middlewares.py`
  (allowlist, rate limit), `progress.py` (one "Searching..." message edited in place),
  `runner.py` (polling now; `run_webhook` is a documented stub), `main.py` (real wiring).
- Tests: relevance, filters, orchestrator with fake sources, a full bot-flow test that feeds real
  updates through the real dispatcher with a recording Telegram session, formatting limits,
  services, registry. `tests/test_user_store.py` needs Postgres (CI only).

Not verified (do this first when Docker/Postgres or a free evening is available):
- A real run: `.env` has `BOT_TOKEN`, Telegram API creds and groups, but the local Postgres
  `aggregator` role fails auth and the Telethon session has not been created. Run migrations
  (`alembic upgrade head`), `make telegram-login` equivalent, then `aggregator-indexer` and
  `aggregator-bot`, and try "iphone 13" end to end. Bazaraki live scraping has never been run
  from the bot either.
- `DbUserStore` / `DbSearchLogStore` / `DbExpansionStore` SQL (CI will run them).
- **`ALLOWED_USER_IDS` is empty in `.env`: the bot is public until you add your Telegram id.**
- With no `ANTHROPIC_API_KEY` the rule-based fallback is used (works, but fewer variants).

### Milestone 5: status

Local gate green (207 passed, 11 skipped = DB tests).

`query/` package (strict mypy):
- `normalize.py`: `normalize_input` (cache key: casefold, NFKC, punctuation stripped except `+ . -`,
  capped 128 chars) and `clean_expansion` (dedupe/cap lists, `variants` never repeat `normalized`,
  `negative_terms` never contain a word the user searched for).
- `fallback.py`: `expand_with_rules` (stop words EN/RU, spec tokens like `128gb`, brand map, EN<->RU
  glossary variants, category-based negative terms).
- `llm.py`: `AnthropicExpander` (`messages.create` with `output_config.format` JSON schema, user text
  wrapped in `<query>`, `asyncio.wait_for` hard timeout, `max_retries=0`, any failure ->
  `LLMExpansionError`). Model comes from `ANTHROPIC_MODEL`.
- `store.py`: `ExpansionStore` protocol, `DbExpansionStore` (`query_expansions` table, upsert, 30-day
  max age, `original` is not stored), `InMemoryExpansionStore`.
- `service.py`: `QueryExpander.expand(text)`: memory cache (1h) -> DB store -> LLM -> rules.
  Never raises for a non-empty query (empty -> `ValueError`; bot should reject it earlier). Fallback
  results are deliberately NOT cached. Store errors are logged and ignored.
  `build_query_expander(settings, store)` is the wiring entry point for milestone 6.

Notes for milestone 6:
- Not verified against the real API (no key locally): only a fake client. First real run with an
  `ANTHROPIC_API_KEY` should confirm the `output_config` schema is accepted and `claude-haiku-5-5` is
  the right model id.
- Apply `negative_terms` to the listing **title** only, and weigh them (a title like "iphone 13 with
  charger" is a legitimate listing; "iphone 13 charger" is not).
- Cap user query length in the bot (~100 chars); `normalize_input` truncates to 128 anyway.

### Milestone 4: status

All code is written, committed (`10564ac`, not pushed) and the local gate is green.

What exists:
- `domain/pricing.py`: `parse_price` (shared with Bazaraki) and `extract_price` for free text.
- `sources/telegram/parser.py`: `parse_message` -> title/description/price/city/`is_sold`/`is_wanted`.
- `sources/telegram/ingest.py`: pure per-message decision (`ingest_message`): store, store inactive
  (sold), skip wanted, skip empty. `deactivate_existing=False` for backfill (no pointless UPDATEs).
- `db/repositories.py`: `ListingRepository` (`upsert`, `mark_deleted`, `deactivate_older_than`,
  `search`). Search = `search_vector @@ plainto_tsquery('simple')` OR `title %> term`; FTS hits
  rank above fuzzy ones, then word similarity, then newest.
- `sources/telegram/source.py`: `TelegramSource` (DB only, wraps failures in `SourceError`).
  `search_terms` moved to `sources/base.py` and shared with Bazaraki.
- `sources/telegram/indexer.py`, `client.py`, `login.py`, `main.py`: Telethon indexer (group
  resolution, backfill, NewMessage/Edited/Deleted handlers, 6-hourly retention), `make
  telegram-login`, exits with a clear message if the session is not authorized.
- docker-compose: one-shot `migrate` service; bot and indexer wait for it; both have healthchecks.
- CI: Postgres 16 service + `TEST_DATABASE_URL`; DB tests skip locally without it.
- Tests: parser, ingest + handlers with fake Telethon objects, group normalisation, source, and a
  read-only guard (`tests/test_telegram_readonly.py` greps for send/edit/delete/join calls).

Still to verify (needs Postgres; the user chose to skip local DB verification for now: Docker
Desktop was not running and the local Postgres 18 credentials are unknown. Verification will happen
in CI, or later with a throwaway `postgres:16-alpine` container and `TEST_DATABASE_URL`):
- `tests/test_repositories.py` has never run. First CI run is the real check of the SQL
  (`%>` operator, `plainto_tsquery(... ::regconfig)`, `ON CONFLICT ... constraint=`, ranking).
  If it fails, fix the repository, not the tests, unless the test expectation is wrong.
- The Telethon wiring itself (real login, backfill, live events) has only been tested with fakes.
  Needs `make telegram-login` with the real account, then running the indexer against
  `TELEGRAM_GROUPS`. The reader account must be a member of each group to receive live updates.
- Backfill is sequential per group before live listening starts; handlers are registered first so
  nothing is missed meanwhile.

## Decisions made (do not re-litigate)

- **Bazaraki ToS:** their terms (about/rules, 5.3.1(f), 4.1) forbid scrapers/bots even though
  robots.txt allows `/search/`. The owner chose: **build it, private use only**. Keep strictly to
  HTML `/search/` pages (never `/api`, never `attrs_*`), low volume, cached, stop on 403, and put a
  prominent warning in the README (not suitable for a public service). Details:
  `docs/research/bazaraki.md`.
- Bazaraki parser reads the advert objects embedded in the Next.js flight data (works for both
  layouts) and raises `SourceError` when a page has none. Posted dates are approximate (relative
  text only).
- Best deals: median from the IQR-filtered sample; candidates must be >= 20% of the median (bait
  floor) so tight clusters still show real discounts.
- City: `UNKNOWN` listings are included in "All Cyprus" only. Unknown-location Bazaraki results from
  a district-scoped request take that district.
- Bare "price 250" with no currency is assumed EUR. Multi-item posts yield only the first price.
- `anthropic_model` default is `claude-haiku-5-5`, overridable via `ANTHROPIC_MODEL`.

## Environment notes

- Local machine: Windows, Python 3.13 (project targets >=3.12; CI/Docker use 3.12), no make, no uv.
  Docker 29 is installed but the daemon was not running; a local Postgres 18 service exists but the
  `aggregator` role in `.env` fails authentication. Use the venv tools directly (see top). DB-backed
  tests (`TEST_DATABASE_URL`, they DROP all tables) are skipped locally.
- `.env` exists locally (gitignored) with `BOT_TOKEN`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`,
  and `TELEGRAM_GROUPS=https://t.me/baraholka_kipr`. Still empty: `ANTHROPIC_API_KEY`,
  `ALLOWED_USER_IDS`. Never print or commit secrets.
- **Running `aggregator-bot` locally starts a LIVE bot** (`@TrevorTheHelp_bot`) on the real token.
  Do not "smoke test" it by running it. In PowerShell, `$env:X=''` DELETES the variable, so
  settings then fall back to `.env`; to blank a value use a different mechanism (or `Settings(
  _env_file=None)` in code). One accidental run happened in milestone 6: ~2 minutes of polling, no
  updates handled, then killed; side effects were only `delete_webhook` + `set_my_commands`.
- selectolax >= 1.0 only has the lexbor backend: `from selectolax.lexbor import ...`.
- Writing files containing Cyrillic through bash heredocs failed once; use the editor tools.
- `claude doctor` in this shell fails ("native binary not installed"): the npm wrapper's postinstall
  never ran. Unrelated to the project; fix with
  `node %APPDATA%\npm\node_modules\@anthropic-ai\claude-code\install.cjs`.

## Quality gate

`ruff check .`, `ruff format --check .`, `mypy` (strict on config, cache, domain, analytics,
search, query, sources.base/registry), `pytest`. All green at the last commit. CI runs the same on
Python 3.12.
