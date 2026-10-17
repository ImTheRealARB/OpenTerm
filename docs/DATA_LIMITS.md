# Data limits

Known limitations, surfaced in the UI where they apply. Updated each phase.

## Providers (verified 2026-10-17)

| Provider | Key | Coverage | Limits and caveats |
|---|---|---|---|
| Yahoo Finance | none | Global equities/ETFs (`.NS` `.BO` `.L` `.T` `.HK` ...), indices `^`, FX `=X`, crypto `-USD` | Unofficial and undocumented; can break or block without notice. Exchange-delayed. `v7/quote` now needs a session crumb (401), so quotes come from `v7/spark` and `v8/chart` metadata, and the day **open** is blank on batch quotes. Intraday lookback: 1m = 7 days, 2-30m = 60 days, 60m = 730 days. |
| Nasdaq.com API | none | Plain US tickers (stocks, ETFs) | Fallback only. **Daily history only.** Delayed. The `lastTradeTimestamp` label can lag the data by a session. ETF responses have no 52-week range. |
| Stooq | none | — | **Retired.** CSV downloads now serve a JavaScript bot check. OpenTerm does not bypass bot protection. |

Non-US symbols currently have **one** zero-key source (Yahoo). If Yahoo is down they show
`PROVIDER DOWN` (or their last cached value, labelled `STALE` with its age). Keyed fallbacks
(Twelve Data, Finnhub) are planned for phase 3.

## Streaming (phase 3)
- Live ticks come from Yahoo's public streamer (`wss://streamer.finance.yahoo.com`), unofficial and
  undocumented. It only sends a message when a price changes, so closed markets show no ticks;
  their rows show the last REST snapshot with its source and age.
- Prices arrive as **float32** and are rounded to the instrument's price hint (2 dp for most), so
  very large prices can be off by the last digit (e.g. BTC at 81,591.72 is exact to ±0.01).
- If the stream is down, the backend **polls REST quotes every 5 s** for subscribed symbols and
  sends only real changes; the UI labels these `POLL`, stream ticks `STREAM`, test data `SYNTHETIC`.
- **Daily charts do not add a new bar from ticks.** Live ticks extend today's bar; the next day's
  bar appears with the next history refresh (F5 or cache expiry), rather than being guessed.

## Descriptions (DES)
- From Yahoo `quoteSummary`, which needs the same cookie + crumb a browser session gets (no bot
  check is involved). Fallback for US symbols: Nasdaq company profile (sector, industry and
  description only; no valuation numbers).
- `EXCHANGE DATA DELAYED N MIN` is the delay reported by the source per exchange.

## Phase 5 sources (verified 2026-10-17)

| Function | Source chain | Limits and caveats |
|---|---|---|
| N (top stories) | Publisher RSS: CNBC, MarketWatch, BBC Business, Economic Times markets, Mint markets (override in `config.yaml` `news.feeds`) | Headlines, the feed's own teaser (max 300 chars, tags stripped) and a link only. Articles open on the publisher's site. Feeds that fail are listed as `NOT ANSWERING`. MarketWatch and Mint sometimes send invalid UTF-8; the bad bytes show as `�`. |
| N (security) | Yahoo headline RSS, then GDELT | Yahoo RSS is unofficial and sparse outside US listings. The GDELT fallback searches the symbol's base as a keyword (3+ letters only). |
| N (keyword) | GDELT DOC 2.0 (English, last 7 days) | GDELT asks for one request every 5 s and answers in 8-12 s from India. It often answers 429 even when calls are spaced; a second search inside 5 s waits for its slot (up to 6 s). |
| MOV | Nasdaq.com market movers (US only) | Includes warrants and penny stocks as Nasdaq reports them. Each tab shows Nasdaq's own "data as of" (tabs can be from different sessions). %CHG on the share-volume tab is derived from the reported last and change. Slow (4-5 s), hence a 12 s timeout. Yahoo predefined screeners returned zero rows on 2026-10-17 (a Saturday, with and without crumb), so they are not used. |
| CRYP | CoinGecko markets (top 50), then Binance `data-api.binance.vision` 24 h tickers | CoinGecko keyless is roughly 5-30 calls/min (backend TTL 60 s). Binance fallback: 22 fixed USDT pairs, prices in USDT, no rank or market cap (blank). Binance rejects the whole call if one pair does not exist. |
| WEI, FX, FXC, CMDTY | Yahoo quotes + stream (same path as Q) | Fixed symbol lists in `frontend/src/functions/boards.ts`, all checked on Yahoo spark. FXC crosses are triangulated through USD from `USDxxx=X` legs; a missing leg leaves the cell blank. Commodity units are contract specs (USC = US cents). |
| WL | SQLite (`watchlists` table) | Up to 500 symbols per list; aliases are resolved like the command line (EURUSD becomes EURUSD=X). |

## Behaviour on failure
- Cached data is served instantly and marked `stale` with its `age_s` while a background refresh runs.
- A provider that fails 3 times in a row, or returns 429, is skipped for 5 s doubling up to 5 min,
  and probed every 30 s until it recovers.
- An unknown symbol is `NO DATA FOR SYMBOL`; it never trips a provider.
- Error responses carry `detail` with each provider's reason (e.g. `gdelt: rate_limited (...)`); the
  N, MOV and CRYP panels show it next to the error.

## Fixture mode
`OPENTERM_FIXTURES=1` replays recorded responses from `backend/tests/fixtures/` (tests and bench).
Only recorded symbols answer; everything else is `NO DATA FOR SYMBOL`. The status bar and SOURCES
show `FIXTURES` while it is on.

## Other
- **Market open/closed lights ignore exchange holidays.** They follow regular weekday sessions only (NY, LN, IN, TK, HK, with lunch breaks for Tokyo and Hong Kong).
- **Browser-reserved shortcuts.** In a normal browser tab, Ctrl+W, Ctrl+T, Ctrl+N and Ctrl+1..9 cannot be intercepted. Use Alt+W and Alt+1..9. The desktop (Tauri) build will not have this limit.

## Phase 6 sources (FA, FIL/SEC, OWN, HDS)

| Function | Source chain | Limits and caveats |
|---|---|---|
| FA | SEC EDGAR XBRL company facts (`data.sec.gov`), US filers only | One call per company serves annual and quarterly views (4-5 MB for large filers, 15 s timeout, backend TTL 6 h). Columns come from each filing's own fiscal labels. Q4 is not filed on its own: it is derived as the fiscal year minus the 9-month YTD and shown with `*`. Free cash flow is computed (operating cash flow minus capex), not reported. A line a company does not tag shows `—`; companies use different tags, so lines are not comparable across companies without care. |
| FIL, SEC | SEC EDGAR submissions index | The most recent filings (a company's `recent` list, up to 300 shown). The document opens on sec.gov in a new tab; filing text is not downloaded or scraped. Backend TTL 15 min. |
| OWN | SEC Form 4 XML (up to the 20 newest filings), Yahoo `insiderTransactions` as fallback | Each Form 4 is parsed once and kept forever (filings never change). Filings that fail to download or parse are counted as `FORM 4 NOT READ`. BOUGHT and SOLD total only open-market codes P and S; grants, option exercises and gifts are listed but not totalled. Yahoo's fallback has no Form 4 link for most rows and about 80 rows covering roughly two years. Backend TTL 1 h. |
| HDS | Yahoo `quoteSummary` (institutionOwnership, fundOwnership, majorHoldersBreakdown) | Top 10 institutions and top 10 funds only. Holders come from 13F filings, which are quarterly and filed up to 45 days after quarter end, so positions can be months old; the `REPORTED` column shows each holder's date. Needs the Yahoo cookie + crumb (see Yahoo notes). Works for most US listings, thin elsewhere. Backend TTL 6 h. |

- **SEC fair access:** at most 10 requests per second per client and a declared `User-Agent` with a contact. OpenTerm sends
  at most 8 per second (token bucket, burst 8). Set `SEC_USER_AGENT="Your Name you@yourdomain"` in `.env`. Without it a
  generic agent is sent, SEC may answer 403, and FA, FIL and OWN show `PROVIDER DOWN` with the instruction to set it.
  The address is read from the environment only; it is never written to the repo.
- **US filers only:** non-US listings (`.NS`, `.L`, ...), indices, FX, futures, crypto and funds without 10-K/10-Q show
  `SEC DATA COVERS US FILERS ONLY`. That is a coverage limit, not an error. HDS and Yahoo-based OWN may still answer.
- **Ticker to CIK** uses SEC's `company_tickers.json`, cached in memory for 24 h. Class shares map `BRK.B` and `BRK-B` to the same filer.

## Phase 7: macro (FRED, MACRO, RATES, ERN, ECO)
Probed 2026-10-17. All of it works with zero keys except FRED search and series titles.
- **FRED values (keyless).** `fred.stlouisfed.org/graph/fredgraph.csv?id=X[&cosd=YYYY-MM-DD]`. Values only: no
  title, units or frequency (OpenTerm adds built-in titles for the ~20 series in MACRO's list; any other id shows
  "no title or units"). Missing observations are empty fields and stay missing (shown as a count, never filled).
  Unknown id = 404. **A browser User-Agent makes this host hang**, so the adapter sends `OpenTerm/0.1`. Several ids of
  mixed frequency come back as a zip and same-frequency ids ignore `cosd`; the adapter fetches one id per call and
  slices to the range itself. Updated by FRED on each series' release schedule: daily series lag by about a day,
  monthly ones by weeks.
- **FRED API (`FRED_API_KEY`, free).** Adds titles/units/frequency, MACRO search across ~800k series and a release
  calendar fallback. 120 requests/min upstream; OpenTerm paces at 2/s. The key travels in the query string, so error
  text is redacted before it reaches the UI or the log. No recorded answers exist for the keyed paths (no key was
  available): the `fred_api_docshape_*` fixtures are built from the documented response shape, labelled as such in
  `providers/fixtures.py`. Treat the keyed path as untested against the live API.
- **RATES (Treasury).** `home.treasury.gov` par yield curve CSV, one file per calendar year, newest row first. The
  curve date is the last business day published (usually yesterday), shown on the panel with a day count when it is
  more than 4 days old. 1.5M exists only since 2025-02. The 1Y comparison needs last year's file; if that file fails
  the panel says so and drops the 1Y column. Fallback when Treasury is down: FRED `DGS*` series (fewer tenors,
  same par yields), flagged on screen.
- **ERN (Nasdaq).** `api.nasdaq.com/api/calendar/earnings?date=`: one call per day, 1-4 s. Future days carry the
  consensus EPS and last year's figure; past days carry reported EPS and surprise. Weekends and holidays answer
  `rows: null`, shown as an empty day. Times are only pre-market / after-hours / not supplied. Estimates come from
  Nasdaq's data vendor and are not verified by OpenTerm. Days further than 400 days from today are refused.
- **ECO (BLS + BEA).** Official ICS schedules, keyless: BLS `bls.ics` (current through 2026-12 when probed) and BEA's
  subscription feed (through 2027-12). They list **release dates and times only: no forecasts, no actuals, no
  previous values**. Not covered: FOMC and Fed releases, Census, ISM and other private surveys. "MAJOR" is a name
  match on a short list of market-moving releases, not an importance rating from the agencies. BLS returns 403 unless
  the User-Agent names a contact (`SEC_USER_AGENT` in `.env`); BEA times are UTC and are shown in US Eastern. If one
  agency's feed is down the panel says which one is missing.
- **Cache TTLs (config.yaml):** FRED values 1 h, FRED search 24 h, curve 30 min, earnings 15 min, calendar 6 h.
