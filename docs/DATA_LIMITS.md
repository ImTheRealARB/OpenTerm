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

## Behaviour on failure
- Cached data is served instantly and marked `stale` with its `age_s` while a background refresh runs.
- A provider that fails 3 times in a row, or returns 429, is skipped for 5 s doubling up to 5 min,
  and probed every 30 s until it recovers.
- An unknown symbol is `NO DATA FOR SYMBOL`; it never trips a provider.

## Fixture mode
`OPENTERM_FIXTURES=1` replays recorded responses from `backend/tests/fixtures/` (tests and bench).
Only recorded symbols answer; everything else is `NO DATA FOR SYMBOL`. The status bar and SOURCES
show `FIXTURES` while it is on.

## Other
- **Market open/closed lights ignore exchange holidays.** They follow regular weekday sessions only (NY, LN, IN, TK, HK, with lunch breaks for Tokyo and Hong Kong).
- **Browser-reserved shortcuts.** In a normal browser tab, Ctrl+W, Ctrl+T, Ctrl+N and Ctrl+1..9 cannot be intercepted. Use Alt+W and Alt+1..9. The desktop (Tauri) build will not have this limit.
