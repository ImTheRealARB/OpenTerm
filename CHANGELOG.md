# Changelog

Format: newest first, one section per phase. Details for each release are in `docs/RELEASE_NOTES.md`.

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
