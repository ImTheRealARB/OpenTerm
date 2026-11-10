# OpenTerm 0.1.0: release notes

OpenTerm is a keyboard-first, open-source market terminal: amber on black, a command line and tiled panels.
Free data only; no key is needed to start (SEC EDGAR wants a contact string in `SEC_USER_AGENT`; the official FRED API
uses `FRED_API_KEY`, the keyless FRED CSV is used otherwise).

## Install and run
- **From source** (step by step for beginners in the [README](../README.md#install)): `.\scripts\setup.ps1` (light install, about 330 MB; `-Dev` adds test tools and Chromium), then `.\scripts\install-launcher.ps1` once, then just type `openterm` (or run `.\scripts\start.ps1`) (builds, serves on <http://localhost:8000>,
  opens the browser). For development with hot reload: `.\scripts\dev.ps1` and <http://localhost:5173>.
  Commands to try: [COMMANDS.md](COMMANDS.md).
- **Docker** (built and run under compose 2026-11-10, see `docs/DESKTOP.md`): `docker compose up --build`, then <http://localhost:8000>.
- **Desktop** (Linux deb / AppImage built 2026-11-10, unsigned; Windows and macOS untested; see `docs/DESKTOP.md`): Tauri window around the same backend, which it starts from a repository checkout (the backend is not bundled yet).

## What is in it
### Phase 1: shell
Top bar with clocks and market lights, command line with fuzzy autocomplete and history, tiling workspace
(split, close, focus, resize, maximize, per-panel history), `keybindings.json`, `PERF` monitor, bench gate, CI.
### Phase 2: data core
Yahoo and Nasdaq adapters behind a router with fallback and circuit breaker, token buckets, LRU + SQLite cache,
stale-while-revalidate envelopes, request coalescing, `SOURCES` and `LOG` screens, fixture mode for tests.
### Phase 3: first functions
Live streaming with REST poll fallback, `Q` quote monitor, `QR`, `DES`, and `GP` charts (candle/OHLC/line/area,
log scale, compare, SMA/EMA/Bollinger/RSI/MACD/VWAP, keyboard pan and zoom) on a canvas virtualized grid.
### Phase 4: workspace
Named layouts (`LAYOUT`, `MONITOR`, `Ctrl+S`, `Ctrl+O`) and command history stored in SQLite.
### Phase 5: boards and lists
`WL` watchlists, `N` news (RSS, Yahoo RSS, GDELT), `MOV` movers, `CRYP` crypto, boards `WEI` `FX` `CMDTY`,
`FXC` cross-rate matrix.
### Phase 6: filings and fundamentals
`FA` financial analysis from SEC XBRL company facts (income statement, balance sheet, cash flow; annual or quarterly, derived
quarters marked), `FIL` / `SEC` filings list with form filters, `OWN` insider transactions read from Form 4, `HDS` institutional and fund
holders (Yahoo). US filers only.
### Phase 7: macro and calendars
`FRED` plots any series, `MACRO` browses a curated list (search needs a FRED key), `RATES` Treasury yield curve with 3M10Y / 5S30S / 2S10S
spreads, `ERN` earnings calendar by day, `ECO` release dates from BLS and BEA (dates and times only, no forecasts or actuals).
### Phase 8: portfolio and alerts
`PORT` portfolios with average-cost lots, live P&L, FX conversion to a base currency and CSV import/export; `ALRT` price and percent
alerts evaluated in the browser on live ticks (status-bar flash, rearm). No desktop notifications yet.
### Phase 9: research
`EQS` screener over the US universe with a filter grammar, `CORR` correlation matrix, `COMP` peer comparison with median, `HIST` price
table (adjusted close when available), and CSV export from every table panel (`E` or `Alt+X`).
### Phase 10: settings and packaging
- **`SETTINGS`** panel (stored server-side in SQLite, mirrored in localStorage so the first paint has your theme):
  theme, vim mode, number format (thousands and decimal separators), up to 3 header clocks, chart defaults (range and
  type), poll intervals for news, movers, crypto and sources, keybinding overrides, `RESET`.
  Also settable from the command line: `SETTINGS THEME GREEN`, `SETTINGS VIM ON`, and so on.
- **Themes** `AMBER` (default), `GREEN`, `WHITE` (high contrast), `LIGHT`; `THEME name` switches at once. Grid and
  charts re-read the colours on change. Colour still only carries meaning.
- **Vim mode** (opt-in) in the command line: `Esc` for normal mode, `h l w b e 0 ^ $`, `x D dd dw de`, `i a A I`,
  `cw ce cc C`, `k`/`j` for history; `Enter` always runs. `g`, `G`, `PgUp`, `PgDn`, `Ctrl+D`, `Ctrl+U` move in lists.
- **Keybinding overrides:** rebind any action in `SETTINGS`; conflicts, browser-reserved chords (`Ctrl+W`, `Ctrl+T`,
  `Ctrl+1..9`) and the fixed `Esc` / panel-focus keys are refused with a reason. `SHORTCUTS` shows the effective keys.
- **Packaging:** `Dockerfile`, `docker-compose.yml`, static frontend serving via `OPENTERM_STATIC_DIR`, Tauri scaffold in `desktop/`.

## New since 0.1.0 (2026-11-02 to 2026-11-03, on `main`)
- **GUI mode:** one app, two shells. A new user starts in GUI mode (menu bar, sidebar with search, symbol picker, a toolbar on each panel,
  `Alt+H` help drawer, welcome card and a 2-minute tour). Switch with the `TERMINAL | GUI` status-bar control, `Alt+G` or `SETTINGS MODE`.
  Terminal mode is unchanged. Eight panels (Q, GP, WL, N, WEI, FA, PORT, BT) got clearer loading, empty and error states.
- **MCP server (Phase 17):** `POST /mcp` (loopback only) and a stdio bridge `python -m openterm.mcp`, 17 read-only tools, no order tools. See [MCP.md](MCP.md).
- **Alert delivery (Phase 17):** email (SMTP, TLS always verified), Telegram or a webhook; all off by default; `DLVR` panel with test sends and a delivery log.
- **Daily brief (Phase 17):** movers, alerts, earnings, economic events and headlines with sources; scheduled (off by default); `BRIEF` panel.
- **Strategy editor:** `BT EDIT` is a code editor (CodeMirror 6: Python colours, line numbers) with starter templates
  (SMA cross, RSI mean reversion, breakout) and sandbox errors shown under the offending line while you type.
- Gate: pytest 1708, e2e 226. Startup bundle 119.9 KB gzip (budget 400 KB).

## Known limits
- Docker image and Tauri shell are written but not built or run (no Docker or Rust on the build machine).
- Free sources throttle: GDELT answers slowly and rate-limits; Yahoo needs a cookie and crumb. See `docs/DATA_LIMITS.md`.
- Settings sync is last-write-wins by `updated_at` (single user, one backend).
- No auto-update, no signed installers.
