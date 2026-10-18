# Changelog

Format: newest first, one section per phase. Details for each release are in `docs/RELEASE_NOTES.md`.

## Phase 16: AI layer (in progress)
- Added `AI`: a chat panel over an agent that calls 14 read-only tools in-process (quotes, history, profile, financials, filings, news, screener, research tables, options chain, rates, macro, portfolio, backtest, quant jobs).
  Every answer lists its tool calls (source, age, STALE / FAILED / EMPTY), cites them as [T1], and carries `AI · model · time · MODEL OUTPUT, NOT DATA`; no tool data = `UNGROUNDED`, figures no tool returned = `UNSOURCED NUMBERS`.
  Loop guard (3 failed or empty calls in a row, or the same call twice), context budget, daily spend cap. No order tools exist. No key = `KEY REQUIRED`. `SETTINGS AI` picks the model.
- Added `AI BT <idea>` (drafts a BT rule, validated by the engine parser, shown with its command, never run by the AI), `AI CHART` (the newest GP chart to a vision model), five finance playbooks the agent loads on demand
  (valuation, earnings, options, risk, macro) and a `strategy_check` tool. AI BT drafts rule strings only; `SignalEngine` code drafts are not built.
- Added `AI DOC`: ask questions about one SEC filing (`AI DOC FILING AAPL 10-Q`) or an uploaded TXT / CSV / HTML / DOCX / XLSX / PDF. Local parsing (new dependency: pure-Python `pypdf`), keyword search over chunks,
  chunk citations, the same UNGROUNDED / UNSOURCED checks. Documents stay in memory (last 5). No OCR.
- Recorded with the real OpenRouter key: one plain stream and a tool-call round (the pending Phase 11 recording is done).

## Phase 15: risk, quant library, alphas, Kite
- Added `RISK` (VaR / ES by history, normal and EVT, beta, drawdown, contributions, stress replays of 2008, 2020 and 2022 with COVERAGE, Kupiec / Christoffersen / Basel backtest),
  `PORT OPT` (EQVOL, RP, MV, MAXDIV, HRP, TURN preview; `A` saves `<NAME>.OPT`, never edits the original), `PORT ATTR` (Brinson-Fachler plus TWR / MWR / Dietz / XIRR from a stored valuation table),
  `FACT` (Fama-French 5 + momentum, keyless Ken French data), `QL` (GARCH, OU, cointegration, copula, microstructure, event study, deflated Sharpe), `ALPHA` (29-factor zoo scan: IC, IR, decay,
  alive / reversed / dead, lookahead sentinel test) and `CORR REGIME` (edge density, fused / diffuse episodes).
- The math is the new worker-only `quantlib` package ported from Vibe-Trading (MIT, `THIRD_PARTY.md`); every function runs as a job through `POST /api/quant/{fn}`. History accepts a `20Y` range of daily bars.
- Added `KITE` (Zerodha Kite Connect), READ-ONLY: daily `KITE LOGIN`, status, Indian bars, NFO / MCX chains with OI (`OMON NIFTY.NFO R= Q=`), ticker decoder. Inert without your own key; no order surface exists.
  Its fixtures are doc-shaped, NOT recordings.
- `ALPHA`: `Enter` on a factor shows its formula line (the ported module's docstring, inputs, warm-up). Bench 29 of 29. Checked in the real app: fixture smoke run of every Phase 15 function, and live keyless `FACT AAPL`, `RISK` and `ALPHA TOP100`.

## Phase 14: options, rates, futures
- Added `OMON` (chain with Greeks, OI, volume), `PCR`, `OV` (Black-Scholes, binomial, Heston, barrier, IV solver) and `OSA` (multi-leg payoff, scenario
  grid, Greeks by leg), `OVDV` / `SKEW` (implied-vol surface, quadratic smile never extrapolated), `HIVG` (realised vs implied; IV30 is built from LOCAL
  SNAPSHOTS, so history starts the day you first open it). Crypto options come from Deribit. Yahoo options are keyless; Tradier (`TRADIER_TOKEN`) is an optional fallback.
- Added `RATES` upgrade (EUR, GBP, CAD, JPY curves, Nelson-Siegel fit, FRED OAS credit spreads, Treasury auctions), `CT`, `WIRP`, `COT`, `FXFA`
  (labelled a CIP estimate), `YAS`, `SWPM`, `CDSW`. A missing input makes a model NOT RUNNABLE and lists the fields; nothing defaults silently.
- Quant library (`openterm/quant/`) ported from Vibe-Trading (MIT, `THIRD_PARTY.md`) and cross-checked against Vibe's own numbers. `BT` can run
  options structures from `OSA`, labelled MODEL-PRICED OPTIONS (BLACK-SCHOLES ON HISTORICAL VOL), NOT MARKET QUOTES. Migration 12 adds `iv_snapshots`.

## Phase 13: equity research gaps
- Added `EE` / `EEO` (estimates, revisions, EPS surprises), `ANR` (ratings, targets, rating changes), `MGMT` (officers, governance, proxies),
  `DVD` / `SPLT` / `CACS`, `IPO`, `SI` (short interest and FINRA short volume), `EVTS` (8-K items decoded), `ETF`, `MEMB` (constituents via the
  proxy ETF's N-PORT), `MGR` (13F, quarter over quarter) and `CN` (company news from every source, keyword-scored, NOT A MODEL).
  All work with zero keys (Yahoo `quoteSummary`, Nasdaq, FINRA, SEC); a key unlocks more.
- Added `DCF` / `WACC` / `RV` on the valuation engine ported from Vibe-Trading (MIT): a missing input makes the model NOT RUNNABLE and lists it; opinions
  (ERP, terminal growth, exit multiple) must be typed (`ERP=5.5 G=2.5 EXITX=14`).
- Added the keyed Finnhub and Alpaca sources (set in `APIKEYS`): their headlines join `N` and `CN`, Finnhub backs `ANR` / `EEO` when Yahoo is down, and
  Alpaca keys turn on real-time US last trades (IEX only), labelled `RT IEX`. Without keys nothing changes.
- Added `ALRT NEWS WORD [SYM]`: fires when a newer headline contains the word (checked on each news refresh, every 2 minutes while the app is open).

## Phase 12: backtester (Phase 11, keys and jobs, is on the same branch)
- Added `BT`: rule syntax (`BT AAPL SMA20>SMA50 1D 5Y`), Python strategies (`BT EDIT`, `@name`), saved rules, results with chart, metrics,
  trades and code views, every result labelled HISTORICAL SIMULATION, NOT A FORECAST with its sources, fees and slippage.
- Engines ported from Vibe-Trading (MIT, `THIRD_PARTY.md`): US, UK, Hong Kong, Canada, India, crypto perpetuals with funding, forex,
  global futures, composite baskets. China A, China futures, Korea, Vietnam and Brazil are not built.
- Added `BT MC` / `BT WF` (Monte Carlo trade shuffle, bootstrap Sharpe interval, walk-forward), `BT RUNS` (compare), `BT EXPORT` (CSV, Pine).
- Added `IMPORT` (your own daily bars, labelled LOCAL DATA) and the keyless `binance_klines` source (spot and USD-M candles with funding).
- Added `scripts/gates.mjs` (the five test gates in parallel) and faster test suites.

## After Phase 10: fixes and browser start
- Added `scripts/start.ps1` / `scripts/start`: build the frontend if stale, serve it from the backend on :8000, open the browser.
- Added `docs/COMMANDS.md`, a list of commands to try.
- Fixed: the panel tab named the last ticker on functions that do not use one (FRED, PORT, EQS, SETTINGS ...).
- Fixed: charts of series without volume (FRED) drew a flat line along the bottom.

## Phase 10: settings and packaging
- Added `SETTINGS` and `THEME`: themes (amber, green, white, light), number format, header clocks, chart defaults, poll intervals.
- Added opt-in vim mode for the command line and vim list keys (`g`, `G`, `Ctrl+D`, `Ctrl+U`).
- Added keybinding overrides with conflict and browser-reserved checks.
- Added `/api/settings` (validated, versioned, stored in SQLite `kv`).
- Added `OPENTERM_STATIC_DIR` static serving, `Dockerfile`, `docker-compose.yml`, `.dockerignore`.
- Added the Tauri scaffold in `desktop/` and `docs/DESKTOP.md`.

## Phase 9: research
- Added `EQS`, `CORR`, `COMP`, `HIST` and CSV export.

## Phase 8: portfolio and alerts
- Added `PORT` (CSV import/export) and `ALRT`.

## Phase 7: macro and calendars
- Added `MACRO`, `FRED`, `ECO`, `RATES`, `ERN`.

## Phase 6: filings and fundamentals
- Added `FA`, `FIL` / `SEC`, `HDS`, `OWN`.

## Phase 5: boards and lists
- Added `WL`, `N`, `MOV`, `CRYP`, `WEI`, `FX`, `FXC`, `CMDTY`; pytest-xdist; parallel Playwright.

## Phase 4: workspace
- Added named layouts and SQLite persistence for layouts and command history.

## Phase 3: first functions
- Added live streaming, `Q`, `QR`, `DES`, `GP`, canvas grid.

## Phase 2: data core
- Added Yahoo and Nasdaq adapters, router with fallback, SWR cache, `SOURCES`, `LOG`, fixture mode.

## Phase 1: scaffold
- Added shell UI, tiling workspace, command parser, autocomplete, keybindings, `PERF`, bench script, CI.
