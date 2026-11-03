# Bazaraki: site inspection notes (2026-11-03)

Findings from inspecting the real site, as required by BUILD_PROMPT §5.3. A handful of read-only GET
requests were made: two search pages via curl (User-Agent `TrevorTheHelperBot/0.1 (personal
portfolio project)`), plus robots.txt, the home page and the terms page via the WebFetch tool.

## robots.txt

- `User-agent: *` is `Allow: /`, no `Crawl-delay`.
- Disallowed: `/api`, `/*/api`, `*attrs_*` (attribute-filtered listing URLs), `/?saved_search`,
  profile/author/edit pages and a few real-estate paths.
- Plain keyword search (`/search/?q=...`) and district pages (`/search/<district>/`) are not disallowed.
- `CCBot` and `Bytespider` are disallowed site-wide. `anthropic-ai` and `ClaudeBot` follow the `*` rules.
- **Consequence:** the internal JSON endpoints under `/api` must NOT be used. Only server-rendered pages.

## Terms and conditions (https://www.bazaraki.com/about/rules/)

The terms prohibit automated access. Relevant clauses (as summarised from the page):

- 5.3.1(f): do not "use any robot spider, scraper or other automated means to access Bazaraki
  and collect content for any purpose".
- 4.1: no "bots or spiders" / automated systems on Bazaraki.
- 4: text and data mining of Bazaraki or its databases needs prior written consent.
- 5.3.1(e), 12.1, 12.3: no reproducing, copying, redistributing or creating derivative works from
  Bazaraki content without written consent.

robots.txt permits fetching search pages, but the terms forbid scraping. **A live scraper is
against the site's terms regardless of robots.txt.** This is a legal/ToS decision for the project
owner; see the decision recorded in the README once made.

## Technical structure (if a fetch is ever enabled)

- Next.js app, server-rendered HTML (~0.7-0.9 MB per search page, 60 results/page).
- Search: `https://www.bazaraki.com/search/?q=<query>&page=<n>`.
- City filter is path-based: `/search/<slug>/?q=...` with slugs
  `lefkosia-district-nicosia`, `lemesos-district-limassol`, `larnaka-district-larnaca`,
  `pafos-district-paphos`, `ammochostos-district` (Famagusta).
- The DOM differs by view: the unscoped page renders `CardGridDesktop` cards, the district-scoped
  page renders `BigAdCard` cards. The cards have no posted date.
- Both pages embed the same advert objects in the Next.js flight data
  (`self.__next_f.push([1,"..."])`, key `"adverts"`): `id`, `title`, `description`, `price`
  (`€250` or text), `price_without_currency`, `currency`, `published` (relative: "1 week ago",
  "Yesterday", "12 minutes ago"), `url` (`/adv/<id>_<slug>/`), `location`
  (`Limassol — Limassol Marina`). **The parser reads this** (one code path for both layouts)
  and raises `SourceError` if a page has no advert data, so a layout change fails loudly.
- Validated against two real pages (60 adverts each, all fields present) on 2026-11-03.
  Committed fixtures are small, sanitized reconstructions with invented adverts.
- Searches are fuzzy: "iphone 13" matches ~1000 adverts including accessories, so the relevance filter is required.
