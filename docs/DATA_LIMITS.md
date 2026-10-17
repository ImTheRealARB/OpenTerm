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
