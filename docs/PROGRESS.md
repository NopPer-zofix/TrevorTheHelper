# Progress and resume guide

Spec: `docs/BUILD_PROMPT.md` (milestones in §9). Last updated: 2026-11-03.

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
| 4 | Telethon indexer + message parser + DB search | Code complete, **uncommitted**; DB tests unverified until CI runs |
| 5 | Query expansion (Anthropic + rule-based fallback + DB cache) | Not started |
| 6 | Search orchestrator, relevance filter, bot flow, service layer | Not started |
| 7 | i18n (en/ru), filters, pagination UI, polish | Not started |
| 8 | README (Mermaid diagram, setup, config table, ToS note, roadmap) | Not started |

### Milestone 4: status

All code is written and the local gate is green (173 passed, 10 skipped). **Uncommitted**: commit
as "Milestone 4: Telegram indexer, parser and DB search" once happy.

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

Still to verify (needs Postgres, not possible locally: no Docker, and `pgserver` has no wheel for
Python 3.13):
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

- Local machine: Windows, Python 3.13 (project targets >=3.12; CI/Docker use 3.12), **no Docker, no
  make, no uv, no Postgres**. Use the venv tools directly (see top). DB-backed code can only be
  verified in CI (or with an embedded Postgres) until Docker is installed.
- `.env` exists locally (gitignored) with `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, and
  `TELEGRAM_GROUPS=https://t.me/baraholka_kipr`. Still empty/unknown: `BOT_TOKEN`,
  `ANTHROPIC_API_KEY`, `ALLOWED_USER_IDS`. Never print or commit secrets.
- selectolax >= 1.0 only has the lexbor backend: `from selectolax.lexbor import ...`.
- Writing files containing Cyrillic through bash heredocs failed once; use the editor tools.
- `claude doctor` in this shell fails ("native binary not installed"): the npm wrapper's postinstall
  never ran. Unrelated to the project; fix with
  `node %APPDATA%\npm\node_modules\@anthropic-ai\claude-code\install.cjs`.

## Quality gate

`ruff check .`, `ruff format --check .`, `mypy` (strict on config, cache, domain, analytics,
search, query, sources.base/registry), `pytest`. All green at the last commit. CI runs the same on
Python 3.12.
