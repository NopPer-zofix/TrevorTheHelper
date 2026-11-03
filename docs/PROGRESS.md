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
| 4 | Telethon indexer + message parser + DB search | **In progress** |
| 5 | Query expansion (Anthropic + rule-based fallback + DB cache) | Not started |
| 6 | Search orchestrator, relevance filter, bot flow, service layer | Not started |
| 7 | i18n (en/ru), filters, pagination UI, polish | Not started |
| 8 | README (Mermaid diagram, setup, config table, ToS note, roadmap) | Not started |

### Milestone 4: what exists / what is left

Done (uncommitted work is included in the latest WIP commit):
- `domain/pricing.py`: `parse_price` (shared with Bazaraki) and `extract_price` for free text
  (symbols/words for EUR USD GBP RUB UAH, labelled "цена 250", old-price skipping, ambiguity
  guard: `iPhone 13 250€` / `Sofa 1 200€` return no price rather than a wrong one).
  Tests: `tests/test_pricing.py`.

Left, in this order:
1. `sources/telegram/parser.py`: `parse_message(text)` -> title (first meaningful line, strip
   hashtags/emoji, <=120 chars), description, price via `extract_price`, city via `detect_city`,
   `is_sold` (sold / продано / продан[аоы]? / неактуально, anywhere), `is_wanted` (куплю, ищу, wtb,
   looking for, want to buy, wanted: only within the first ~100 chars). Do NOT match "продаю/продается".
2. `db/repositories.py`: upsert on (source, external_id), `mark_deleted`, `deactivate_older_than`,
   `search(terms, city, max_age_days)` using `search_vector @@ plainto_tsquery('simple', ...)` OR
   `title %> / word_similarity`, ranked, limited. The 'simple' FTS config has no stemming, so the
   trigram branch is what makes "велосипеды" match "велосипед".
3. `sources/telegram/source.py`: `TelegramSource(ListingSource)` reading from the DB (not live).
4. `sources/telegram/indexer.py` + `main.py`: Telethon client; resolve groups; backfill N days
   (`iter_messages`, stop at cutoff, `wait_time=1`); handlers for NewMessage / MessageEdited /
   MessageDeleted. Read-only: never call any send_* method (add a test that greps the source).
   external_id = `<real chat id>:<msg id>` (use `telethon.utils.resolve_id`); url =
   `https://t.me/<username>/<id>` or `https://t.me/c/<id>/<id>` for private groups.
   Wanted posts are skipped (and deactivate an existing row on edit); sold posts are stored with
   `is_active=False`. Invite links (`t.me/+...`) are unsupported: log and skip.
5. `sources/telegram/login.py` + `make telegram-login`: interactive first login (phone, code, 2FA)
   writing the session under `./data/` (Telethon appends `.session`; strip it from
   `TELEGRAM_SESSION_PATH`). `main.py` must exit with a clear message if not authorized.
6. docker-compose: replace `alembic upgrade head` inside `bot` with a one-shot `migrate` service
   that bot and indexer depend on (`service_completed_successfully`) to avoid a migration race;
   add an indexer healthcheck.
7. CI: add a Postgres service; DB tests skip locally unless `TEST_DATABASE_URL` is set.
   Idea for local verification without Docker: `pip install pgserver` in a scratch venv (unverified
   that it ships `pg_trgm`).
8. Tests: message parser (sold / wanted / city RU+EN / price), ingest decisions with fake Telethon
   objects, repository + search against Postgres in CI.

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
