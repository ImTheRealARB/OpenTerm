# Handoff

_Last updated: 2026-10-17, session 4 (Phase 5 committed `4b3814c`; Phases 6-10 built in parallel worktrees, being merged here one phase per commit; Phases 6-9 and the CSV wiring committed; Phase 10 merged, awaiting commit)._

> **Resuming in a new session or account?** Paste the prompt from [RESUME_PROMPT.md](RESUME_PROMPT.md)
> and read "Parallel build of Phases 6-10" below.

## Parallel build of Phases 6-10 (MERGING)
Status: **all five phases were finished in their worktrees (each green in isolation). The lead is merging them here in order
6, 7, 8, 9, 10, one commit each; the user approves every commit. Phases 6-9 are committed (`96d40b9`, `90bffb1`, `1070230`, `b5515ac`); the CSV wiring is committed (`7e3ca69`); Phase 10 is merged and verified, awaiting commit.**
The last column tracks the merge into this worktree.

| Phase | Worktree (under `.claude/worktrees/`) | Branch | Notes file | Merge |
|---|---|---|---|---|
| 6 FA, FIL/SEC, OWN, HDS | `openterm-p6` | `claude/openterm-p6-wip` | `PHASE_6_NOTES.md` | **COMMITTED** `96d40b9` |
| 7 FRED, MACRO, RATES, ERN, ECO | `openterm-p7` | `claude/openterm-p7-wip` | `PHASE_7_NOTES.md` | **COMMITTED** `90bffb1` |
| 8 PORT, ALRT (migrations 6-7) | `openterm-p8` | `claude/openterm-p8-wip` | `PHASE_8_NOTES.md` | **COMMITTED** `1070230` |
| 9 EQS, HIST, CORR, COMP, CSV export | `openterm-p9` | `claude/openterm-p9-wip` | `PHASE_9_NOTES.md` | **COMMITTED** `b5515ac`; CSV hook wired into the Phase 6-8 panels in the follow-up commit |
| 10 SETTINGS, themes, vim, keybinding overrides, Docker, Tauri, release notes | `openterm-p10` | `claude/openterm-p10-wip` | `PHASE_10_NOTES.md` | **MERGED + verified here** (see Phase 10 details); commit pending user approval |

- All five branch from `4b3814c`; their changes are **uncommitted** in their worktrees. Rules they follow:
  [docs/PARALLEL_BUILD.md](docs/PARALLEL_BUILD.md) (append-only "Phase N" blocks in shared files, no migrations except
  Phase 8 at positions 6-7, notes kept current, no commits, light checks only; Playwright and bench run after the merge).
- Each `PHASE_N_NOTES.md` (phase worktree root) has the details; the lead folds it into this file when merging that phase.
- Phase 6 SEC fixtures: the user approved their Gmail as the SEC User-Agent **for fixture recording only**; it
  must never be written into the repo. The app reads `SEC_USER_AGENT` from env.
- Merge plan, in order 6→10, one phase per commit, each fully verified (pytest, ruff, tsc, vitest, all Playwright,
  bench), and the user approves each commit: `git add -A; git diff --cached 4b3814c > pN.patch` in the phase
  worktree, then `git apply --3way pN.patch` in this worktree. After 9: wire the CSV-export hook into 6-8 panels.
  After 10: confirm release-notes bullets for 6-9, then the full perf pass.
- **Backups (nothing is lost if a worktree disappears):** `wip-patches/pN.patch` in this worktree holds each
  phase's full uncommitted diff vs `4b3814c` (incl. new files and fixtures; made with `git add -A` +
  `git diff --cached --binary`). Restore with `git apply --3way wip-patches/pN.patch` on a checkout of `4b3814c`.
  Fixture-recording and patch scripts the agents used are in `wip-patches/` (`p6rec/`, `p7/`, `p10/`, `rec/`,
  `scripts/`). The worktrees' changes are staged (`git add -A`), not committed. Do not run worktree clean-up
  tools or `git worktree remove` on `openterm-p6..p10` until each phase is merged.
- **Use Sonnet subagents, not Opus** (user's request: Opus agents used ~55% of the 5-hour window in 15 min).
  Run at most 2-3 at once and check plan usage between steps.
- Usage rule from the user: when the 5-hour (or weekly) plan window reaches 90%, stop every subagent, update this
  section and `RESUME_PROMPT.md`, and pause.

## Where things stand
- **Phases 1-4 of 10 are built, verified and committed** (`736d6d5`, `3815fdd`, `b6dca4e`, `b72466a`, docs `a8b7c6e`).
- **Phase 5 is committed** (`4b3814c`) in worktree `.claude/worktrees/openterm-phases-5-10-a49ca4`, branch
  `claude/openterm-phases-5-10-a49ca4` (contains Phases 1-4). **Phases 6-9 are committed (`96d40b9`, `90bffb1`, `1070230`, `b5515ac`); CSV wiring `7e3ca69`; Phase 10 is merged and verified, not yet committed.**
- Phases 3 and 4 live on branch `claude/openterm-phase-3-4-621f59` (worktree), **not on `main` yet**.
  The main checkout has the Phase 3 files uncommitted on `main` (identical to `b6dca4e`). To bring
  `main` up to date: discard those local copies on `main` (`git checkout -- .` and delete the untracked
  Phase 3 files), then `git merge claude/openterm-phase-3-4-621f59` (fast-forward). No git remote. The git identity (ankithrbharadwaj) is set for this repo only.
- Latest verification (Phase 10 tree):
  - Backend: 163 pytest passed (`-n auto`, ~25 s), ruff clean.
  - Frontend: 169 vitest passed, tsc clean, 66 Playwright passed (`--workers=8`, ~24 s).
  - Bench: 17/17 budgets PASS on two of three runs, one lone chart-pan miss (see `docs/PERFORMANCE.md` Phase 10).

## Done
| Phase | Contents |
|---|---|
| 1 Scaffold | Shell UI (top bar, command line, clock + market lights, status bar), tiling workspace (split/close/focus/resize/maximize, panel history), command parser `[N:] SEC [MKT] FN [ARGS]`, fuzzy autocomplete, history, `keybindings.json`, PERF HUD/panel, `scripts/bench.mjs`, CI workflow |
| 2 Data core | Provider adapters (Yahoo, Nasdaq), router with fallback + circuit breaker, token buckets, LRU + SQLite WAL cache, SWR envelopes `{data, source, as_of, age_s, stale, fallback_from}`, request coalescing, `/api/quote|history|search|sources|log`, fixture mode, `SOURCES` and `LOG` screens, live ticker search with prefetch |
| 3 First functions | Yahoo protobuf streamer (hand-decoded), REST poll fallback, SYNTHETIC load stream, hub with one upstream subscription per symbol and per-client coalescing; `/api/profile`; frontend tick store (per-frame batching), canvas virtualized `Grid`, `Q` (live monitor), `DES`, `QR`, `GP` (lightweight-charts, indicators in a Web Worker, compare, log, crosshair, keyboard pan/zoom), `PERF GRID/CHART` load views |
| 4 Workspace | SQLite migrations 3-4 (`layouts`, `history`), `backend/openterm/userdata.py`, `/api/layouts[/{name}]` GET/PUT/DELETE, `/api/cmdhistory` GET/POST; `LAYOUT`/`MONITOR` `SAVE|LOAD|DEL name` (bare name = LOAD, bare `LAYOUT` = list panel with J/K, Enter, Del-twice, S), `Ctrl+S` (re-save current named layout, else prompts) / `Ctrl+O` (prompts `LAYOUT LOAD ` with name autocomplete), layout name in the status bar; command history moved to SQLite (batched writes, `sendBeacon` on exit, one-time upload of the old localStorage history); Playwright tests for layouts, history and Ctrl+Shift+Arrows resizing; bench gate for layout load |
| 5 Boards + lists | Watchlists (SQLite, `WL` grammar), news (`N`: RSS / Yahoo RSS / GDELT), `MOV` (Nasdaq movers), `CRYP` (CoinGecko, Binance), boards `WEI` `FX` `CMDTY`, `FXC` cross matrix, shared `quoteRows.ts`; pytest-xdist, fully parallel Playwright |
| 6 SEC + ownership | `FA` (SEC EDGAR XBRL financials: IS/BS/CF, annual/quarterly), `FIL`/`SEC` (filings list), `OWN` (Form 4 insider transactions), `HDS` (institutional + fund holders); providers `sec`, `yahoo_own`; needs `SEC_USER_AGENT` in env |
| 7 Macro | `FRED` (series chart), `MACRO` (curated list + search), `RATES` (Treasury yield curve + spreads), `ERN` (earnings calendar), `ECO` (BLS + BEA release dates); providers `fred`, `fred_csv`, `treasury`, `nasdaq_earnings`, `agency_ics` |
| 8 Portfolio + alerts | SQLite migrations 6-7 (`portfolios`, `alerts`), `PORT` (positions with average-cost lots, live P&L, FX to base currency, CSV import/export), `ALRT` (price / percent alerts evaluated on raw ticks, status-bar flash, rearm) |
| 9 Analysis | `HIST` (price table, ADJ CLOSE when available), `EQS` (screener over the US universe, filter grammar in args), `COMP` (peers + median, 1M-1Y returns), `CORR` (heat matrix); CSV export everywhere via `E` / Alt+X (`tableExport.ts`); providers `nasdaq_screener`, `yahoo_peers` |
| 10 Settings + packaging | `SETTINGS` panel and `THEME` (amber, green, white, light), vim mode for the command line, keybinding overrides, number format, header clocks, chart and poll defaults (`/api/settings`, SQLite `kv`), `Dockerfile` + compose + `OPENTERM_STATIC_DIR`, Tauri scaffold in `desktop/`, `docs/RELEASE_NOTES.md`, `CHANGELOG.md` |

## Phase 10 details (SETTINGS, themes, vim, keybinding overrides, packaging)

**Built and verified (merged from `openterm-p10`):**
- Backend: **163 pytest passed, ruff clean** (+24 in `tests/test_phase10.py`). `settings_store.py` (validates, stores only non-defaults as versioned JSON in `kv` key `settings`),
  `/api/settings` GET / PUT, `config.py` `openterm_static_dir`, `main.py` `mount_static()` (serves the built frontend at `/` when `OPENTERM_STATIC_DIR` is set).
- Frontend: **169 vitest** (+50), **66 Playwright** (+6 `e2e/phase10.spec.ts`), tsc clean.
  - `settings/{schema,runtime,sync,themes,commands}.ts`, `functions/SETTINGS.tsx`, `THEME name` / `SETTINGS KEY VALUE` commands, themes as CSS variable blocks,
    `command/vim.ts` (opt-in), `keys/overrides.ts` (conflicts, browser-reserved chords, fixed Esc / panel focus refused), `functions/listNav.ts` (g/G/PgUp/PgDn in lists),
    `format.ts` number-format wrap, TopBar clock zones, GP chart defaults, `pollMs` for N/MOV/CRYP/sources.
- Packaging (not built here): `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `desktop/` Tauri 2 scaffold, `docs/DESKTOP.md`.
- Docs: `docs/RELEASE_NOTES.md` (Phase 6-9 bullets rewritten against what was built), `CHANGELOG.md`.
- Merge resolution: import lines, the Phase 7/8/9 api blocks and `main.tsx` startup calls were all kept (`startAlerts()`, `pollSources(pollMs("sources"))`, `startSettingsSync()`);
  Shortcuts text lists both the settings hint and Alt+X.

## Phase 9 details (EQS, HIST, CORR, COMP, CSV export)

**Built and verified (merged from `openterm-p9`):**
- Backend: **139 pytest passed, ruff clean** (+13 in `tests/test_phase9.py`).
  - `providers/screener.py`: `NasdaqScreenerProvider` (`screener`, whole US universe as a columnar payload, TTL 15 min) and `YahooPeersProvider` (`peers`, TTL 24 h).
    `DataService.screener()` / `peers()` (peers fall back to the largest same-industry names, `basis: "industry"`); `/api/screener`, `/api/peers?symbol=`.
  - Bars gained optional `adj` (adjusted close; `models.py` 1 line, `yahoo.py` `bars_from_chart` reads `adjclose`).
  - Fixtures: `nasdaq_screener_trimmed.json` (476 rows trimmed from the real download), `yahoo_recs_aapl.json`, `yahoo_recs_empty.json`.
- Frontend: **119 vitest** (+28: `csvText`, `eqsFilter`, `corrMath`), **59 Playwright** (+13 `e2e/phase9.spec.ts`), tsc clean.
  - Pure: `csvText.ts` (`csv.ts` delegates to it), `functions/eqsFilter.ts` (grammar `SECTOR=TECH MCAP>10B PCT>2 PRICE<50 VOL>1M COUNTRY=US SORT=PCT`),
    `functions/corrMath.ts` (log returns, date alignment, Pearson, heat bands, `parseCorrArgs`), `functions/returns.ts` (`periodReturn`, `histRows`, `histArgs`).
  - Panels: `HIST.tsx` (D/W/MO, Enter = GP), `EQS.tsx` (Enter = DES; parse errors shown in red, the parsed clauses still run), `COMP.tsx` (SELF, peers, `MEDIAN OF n PEERS`),
    `CORR.tsx` (DOM table up to 20x20, H/J/K/L cursor, Enter = GP pair).
  - CSV export: `functions/tableExport.ts` (`useCsvExport`, `gridCsv`, `exportPanelCsv`), binding `exportCsv` = **Alt+X** + `E` panel key. Migrated: Q, WL, MOV, CRYP, Board (WEI/FX/CMDTY), FXC, N, Layout, Sources + the 4 new panels.
- **CSV hook (now applied to the Phase 6-8 panels; recipe for new panels):** `import { gridCsv, useCsvExport } from "./tableExport";`, then after `rows` is computed
  `useCsvExport(panelId, () => gridCsv("FA_AAPL", COLUMNS, rows));` (non-`Grid` panels return `{ name, header, rows }`, `null` while loading;
  `{ panelKey: false }` as 3rd arg if the panel already uses E); add `E CSV` to the hint line; e2e: press `e`, `waitForEvent("download")`.
- Merge resolution: api.py (screener route joined to the Phase 6 start, peers appended), service.py (Phase 9 methods kept inside `DataService`, the Phase 7 imports
  block stays last), `net/api.ts` (both objects closed), registry takes Phase 9's four lines, `test_api.py` pin lists all phases, config.yaml/main.py/styles.css/DATA_LIMITS keep every block.

## Phase 8 details (PORT, ALRT)

**Built and verified (merged from `openterm-p8`):**
- Backend: **126 pytest passed, ruff clean** (116 + 10 in `tests/test_phase8.py`; `test_userdata.py` migration pin updated).
  - Migration 6 `portfolios (name PK, base, positions JSON, updated_at)`, migration 7 `alerts (id, symbol, op, unit, value, status, created_at, triggered_at, trigger_price)`.
  - `portfolio.py` CRUD with average-cost lots; `/api/portfolios[/{name}]` GET / PUT / PATCH `{add, set, remove, base}` / DELETE;
    `/api/alerts` GET / POST, `/api/alerts/{id}` DELETE, `/{id}/trigger`, `/{id}/rearm`, `DELETE /api/alerts?status=triggered`.
- Frontend: **91 vitest** (+25), **46 Playwright** (+6 `e2e/phase8.spec.ts`), tsc clean.
  - Pure modules `command/portfolioArgs.ts`, `command/alertArgs.ts`, `functions/portfolioCsv.ts`, `functions/portfolioMath.ts`;
    `command/portfolios.ts`, `command/alerts.ts` (engine), `execute.ts` PORT/ALRT block, `api8` block in `net/api.ts`.
  - `PORT.tsx`: ADD lots with cost, RM, D/U confirm + undo, EXPORT download, V paste + preview + merge; mixed currencies convert to the
    base with live Yahoo `CCYBASE=X`, labelled (no rate = per-currency subtotal, excluded from the total).
  - `ALRT.tsx`; the engine starts in `main.tsx` (`startAlerts()`), listens through `onRawTicks` in `state/ticks.ts`, flashes via `components/AlertFlash.tsx` in `StatusBar`.
    Alerts fire once, R rearms, C clears. Evaluation is frontend-only (the backend never watches prices).
- Merge fixes: api.py and `net/api.ts` Phase 7/8 blocks joined (restored the closing `return error(e)` / `};`); registry takes Phase 8's PORT and ALRT lines;
  `phase5.spec.ts` FXC assertion now retries (`toPass`) because it raced the frame flush once Phase 8's startup work shifted timing.

## Phase 7 details (FRED, MACRO, RATES, ERN, ECO)

**Built and verified (merged from `openterm-p7`):**
- Backend: **116 pytest passed, ruff clean** (90 + 26 in `tests/test_phase7.py`, which pins "today" to 2026-10-17 via `macro.ny_today`).
  - `providers/macro.py`: parsers + providers `fred` (official API, needs `FRED_API_KEY`; inactive without it, SOURCES shows KEY REQUIRED),
    `fred_csv` (keyless `fredgraph.csv`), `treasury` (par yield curve CSV, one file per year), `nasdaq_earnings`, `agency_ics` (BLS + BEA ICS feeds).
  - `/api/fred?id=&range=`, `/api/macro?q=`, `/api/rates`, `/api/earnings?date=`, `/api/eco?start=&days=`. Capabilities and orders in `config.yaml`
    (`fred_series` [fred, fred_csv], `fred_search` [fred], `yield_curve` [treasury, fred_csv], `earnings` [nasdaq_earnings], `eco_calendar` [agency_ics, fred]).
  - `providers/__init__.py` re-binds `keyed_status` (adds a `fred` KEY REQUIRED row) and pops `fred` from `KEYED`; `fixtures.py` wraps `_route`.
  - 38 fixtures recorded 2026-10-17 from the live sites (FRED CSV x20, Treasury 2025/2026, Nasdaq earnings x3, BLS/BEA ICS, real FRED 400);
    the keyed FRED API shapes are built from the docs (no key available), so live behaviour with a key is untested.
- Frontend: **66 vitest** (+20 `macroArgs.test.ts`), **40 Playwright** (+11 `e2e/phase7.spec.ts`), tsc clean.
  - `FRED.tsx` plots through `ChartView` (o=h=l=c=value; gaps skipped and counted); `MACRO.tsx` without a key shows the built-in list
    and filters locally; `RATES.tsx` derives 3M10Y / 5S30S / 2S10S spreads, Enter plots the matching `DGS*` series;
    `ERN.tsx` args TODAY/TOMORROW/YESTERDAY/+N/-N/YYYY-MM-DD, Left/Right change the day; `ECO.tsx` has dates and times only (BLS + BEA), MAJOR is a name match;
    `macroUi.tsx` shared status/error pieces; `macroApi` block in `net/api.ts`.
  - `ChartView.tsx` got an optional `readoutLabel` prop (crosshair readout `<date> <label> <value> <pct>`), used by FRED.
- Merge resolution: api.py hunks interleaved (6 then 7), `test_api.py` pin lists both phases, registry keeps Phase 6 HDS/OWN and Phase 7 RATES/ERN loads,
  `net/api.ts` needed the closing `};` of `secApi` restored.

## Phase 6 details (FA, FIL/SEC, OWN, HDS)

**Built and verified (merged from `openterm-p6`):**
- Backend: **90 pytest passed, ruff clean** (66 old + 24 in `tests/test_phase6.py`).
  - `providers/sec_parse.py` (pure parsers: `parse_companyfacts` with tag fallbacks per period, dedup by period + latest filed,
    period labels from each filing's own fy/fp, derived quarters = YTD minus shorter YTD, FCF computed; `parse_submissions`;
    `parse_form4`), `providers/sec.py` (`SecProvider`, name `sec`: fundamentals, filings, insiders; token bucket 8/s;
    ticker to CIK from `company_tickers.json` cached 24 h in memory; non-US symbols unsupported),
    `providers/ownership.py` (`YahooOwnProvider(YahooProvider)`, name `yahoo_own`: holders, insiders via quoteSummary; yahoo.py untouched).
  - `service.py` Phase 6 block: `fundamentals`, `filings`, `insiders`, `holders`; parsed Form 4s cached per accession in `cache` (`f4:<accn>`).
  - `/api/fa?symbol=&period=A|Q`, `/api/filings?symbol=&form=`, `/api/insiders?symbol=`, `/api/holders?symbol=`.
    TTLs in `config.yaml`: facts 6 h, filings 15 min, insiders 1 h, holders 6 h.
  - **SEC needs `SEC_USER_AGENT` in env** (default is empty; `config.py` changed from a placeholder; the old placeholder still counts as unset).
    Empty means SEC may answer 403; the error text and SOURCES `terms` say so. The repo never contains an address.
  - Fixtures (real responses, trimmed to the mapped tags / 60 recent filings): `sec_facts_aapl|msft`, `sec_company_tickers`,
    `sec_subs_aapl|msft`, `sec_form4/*` (20 AAPL Form 4s), `yahoo_holders_aapl`, `yahoo_insiders_aapl`.
  - Shared-file edits: `config.py` (1 line), `main.py` (2 lines under `# --- Phase 6`), `service.py` (import + appended methods),
    `api.py`, `providers/__init__.py`, `fixtures.py` (2-line hook at top of `_route` + appended block), `config.yaml`, `test_api.py` (pinned provider set).
- Frontend: **tsc clean; 46 vitest** (36 + 10 in `functions/secTables.test.ts`), **29 Playwright** (23 + 6 in `e2e/phase6.spec.ts`).
  - `functions/secTables.ts` (payload types + shaping for all four panels), `functions/secPanel.tsx` (envelope hook, header,
    `ErrorLine` with the `SEC_USER_AGENT` hint), panels `FA.tsx`, `FIL.tsx` (also serves `SEC`), `OWN.tsx`, `HDS.tsx`; `net/api.ts` `secApi` block; registry lines.
  - FA keys: 1-3 / Tab statement (IS, BS, CF), A / Q annual or quarterly, H / L scroll older / newer periods, J/K, E CSV, F5.
    Args: `AAPL FA Q CF`. Derived quarters carry `*`; negatives are red.
  - FIL keys: 1-6 / Tab form filter (ALL, 10-K, 10-Q, 8-K, 4, DEF 14A), Enter / O opens the document, I the filing index, E CSV.
    Any other form works as an argument (`AAPL FIL 424B2`).
  - OWN keys: M toggles open-market (P/S) only, Enter opens the Form 4, E CSV; shows `N FORM 4 NOT READ` when some failed.
  - HDS: cursor skips section header rows (`navKey` skip callback). No panel polls; F5 refreshes. US-only coverage note is warning-coloured.
- Merge fix: `e2e/cmdline.spec.ts` asserted FA shows `NOT BUILT YET (PHASE 6)`; that line was removed (the header assertion stays).
- Not run against the live network (tests use fixtures). Live SEC calls need `SEC_USER_AGENT`.

## Phase 5 details (WL, N, WEI, MOV, FX/FXC, CRYP, CMDTY)

**Built and verified:**
- Backend: **66 pytest passed, ruff clean** (42 old + 24 in `tests/test_phase5.py`).
  - Migration 5 `watchlists`; `userdata.py` watchlist CRUD (max 500 symbols, aliases resolved, deduped);
    `/api/watchlists[/{name}]` GET / PUT `{symbols}` / PATCH `{add, remove}` (add creates) / DELETE.
  - `providers/news.py`: `rss` (5 publisher feeds, merged newest first, partial failures listed in `failed`),
    `yahoo_rss` (per-symbol, publisher = link domain), `gdelt` (keyword; `max_wait` 6 s, `timeout` 20 s, throttle text = rate_limited).
    `/api/news` (`?symbol=` | `?q=` | none = top), TTL 120 s, not found = `NO HEADLINES FOUND`.
  - `nasdaq.movers()` + `/api/movers` (tabs GAINERS LOSERS ACTIVE DOLLAR NDX100, per-tab "data as of"), TTL 60 s.
  - `providers/crypto.py`: `coingecko` then `binance` (USD/USDT only); `/api/crypto?vs=` (allowed list in `crypto.VS`), TTL 60 s.
  - Provider base: `get_bytes`, per-class `timeout` and `max_wait`. Error bodies now include `detail` (each provider's reason).
  - Fixtures recorded from the real endpoints (see `providers/fixtures.py` `PATHS`, `YAHOO_RSS`, `GDELT`, `COINGECKO`);
    `yahoo_spark.json` now also holds all 74 board symbols. `config.yaml`: new fallback orders, TTLs, `news.feeds` comment.
  - Existing tests changed only where they pin the provider set / migration list (`test_api.py`, `test_userdata.py`).
- Frontend: **tsc clean; vitest 36 passed** (24 old + `command/watchlists.test.ts`, `functions/boards.test.ts`).
  - `command/watchlistArgs.ts` (pure parser) + `command/watchlists.ts` (API actions, `watchlistList`, `watchlistVersion` stores);
    `execute.ts` handles `WL ...` (edit then show the list; no duplicate history entry if the panel already shows it);
    command-line autocomplete for `WL <name>` / `WL DEL <name>`; prefetch now only for RECENT/SEC suggestions (was also prefetching layout names).
  - `Grid` mirrors the selected row into `.grid .sr`. `functions/quoteRows.ts` extracted from Q (Q refactored onto it, same behaviour).
  - Panels written: `WL.tsx` (index with Del-twice delete; list view with D remove, U undo, A add, S sort, E CSV),
    `N.tsx` (Enter opens the article in a new tab, NEW items highlighted, 60 s poll, F5 fresh, error + detail),
    `MOV.tsx` (1-5 / Tab switch tabs), `CRYP.tsx` (Enter = `SYM-USD GP`), `Board.tsx` + `WEI.tsx` `FX.tsx` `CMDTY.tsx`
    (sections skipped by J/K, Enter = GP), `FXC.tsx` (cross matrix, recomputed on leg ticks, Enter = GP vs USD).
  - `format.ts` `fmtRate`; `api.ts` news/movers/crypto/watchlist calls (`fresh` flag skips the client cache); styles `.sr .tabs .summary`.
  - `functions/registry.ts`: all eight wired with `load` and `argsSchema`.
  - `e2e/phase5.spec.ts` (8 tests, mocked routes + WebSocket), green.

**Bench baseline for Phase 8** (Phase 7 tree figures are in `docs/PERFORMANCE.md`; this is the Phase 6 tree, 2026-10-17): 17/17 PASS. Bundle 85.0 KB gz; backend p95
health/quote/history 0.7/0.7/1.9 ms; cold start 92.3 ms; keystroke 14.4 ms (9.8 under load); cached / cold-network
command to paint 18.5 / 18.1 ms; tick-to-pixel 38.2 ms; frame p95 16.7 ms everywhere; long tasks 0; heap 5.1 MB;
ticks 4,000/s; layout load 36.3 ms. (Phase 5 baseline: 84.8 KB, 37.5 ms tick-to-pixel, 35.8 ms layout.)

## Next
Phases 6-10 in order:
- 6: done (merged, see Phase 6 details).
- 7: done (merged, see Phase 7 details).
- 8: done (merged, see Phase 8 details). Desktop notifications were not part of the build: alerts flash in the status bar.
- 9: done (merged, see Phase 9 details). CSV export (`E` / Alt+X) is wired into every table panel, Phase 6-8 included (FA, FIL, OWN, HDS, FRED, MACRO, RATES, ERN, ECO, ALRT via `useCsvExport`); PORT keeps its own `E`/EXPORT, which writes a re-importable portfolio CSV.
- 10: done (merged, see Phase 10 details). Remaining: ask the user to delete `wip-patches/` and `RESUME_PROMPT.md`, then merge to `main` (see the notes below).

## Decisions already made (don't relitigate)
- Stooq is dropped (bot check). The zero-key chain is Yahoo, then Nasdaq (US only, daily history only).
- Keystroke echo is gated at 16.7 ms (one 60 Hz frame), measured from keydown to the start of the next frame.
- Frame time is gated at p95 < 20 ms (60 Hz = 16.7 ms; above 25 ms is a dropped frame).
- Backend latency is gated server-side.
- 9 panels is the maximum (focus-by-number 1-9). The bench runs the 200-symbol load over 9 panels.
- Memory budget is checked as JS heap. Whole-process memory waits for the Tauri build.
- No React.lazy/Suspense for panels (300 ms reveal throttle). Use the registry loader.
- Daily charts never invent a new bar from ticks. Intraday bars are bucketed.
- Lightweight Charts attribution is text (in the GP status line and the README), with the logo off.
- Command history lives on `/api/cmdhistory` (`/api/history` is price bars). Table name is `history`.
- Named layouts are in SQLite. The live (unnamed) workspace still autosaves to localStorage so cold
  start never waits on the backend; recent-securities autocomplete hints also stay in localStorage.
- A saved layout keeps only each panel's current view (no back/forward history). Loading validates
  the tree in the frontend (`state/layoutState.ts`); unknown functions become empty panels.
- Layout load is gated at 100 ms (the cached-command budget). Layout names: 1-32 of A-Z 0-9 _ . -, uppercased.
- Watchlists are in SQLite (same name rules as layouts). Grammar: `WL`, `WL NAME`, `WL NAME ADD|RM SYM...`,
  `WL DEL NAME`; `AAPL WL TECH ADD` adds the typed security, never the panel's sticky one.
- MOV uses Nasdaq only (Yahoo predefined screeners returned empty results on 2026-10-17). US only.
- N shows headline, teaser and link only; Enter opens the publisher's page in a new tab. `N` with a sticky
  security shows that security's news; `N TOP` forces top stories; `N words` is a GDELT search.
- CRYP polls REST (CoinGecko, then Binance); it does not mix in Yahoo stream ticks. Enter charts Yahoo `SYM-USD`.
- FXC crosses are triangulated through USD and labelled so. Boards (WEI, FX, CMDTY) are fixed lists in `boards.ts`.
- Rate-limited providers still surface as `PROVIDER DOWN` (pinned by `test_core.py`); the reason is in `detail`.

## Risks / open items
- Yahoo endpoints are unofficial (stream, spark, chart, quoteSummary crumb flow) and can break without notice. Non-US symbols have no zero-key fallback yet.
- Market-hours lights ignore holidays.
- If the backend is down at page load, command history starts empty for that session (it is not
  re-fetched on reconnect); new commands are still kept and uploaded once the backend answers.
- The CI workflow has never run (no remote). Bench timing on GitHub runners is untested.
- Shell scripts `scripts/setup` and `scripts/dev` are untested on macOS/Linux.
- GDELT throttles hard (429s even when spaced). Its fixture `gdelt_nvidia.json` is a real 5-article answer captured
  while probing; `gdelt_429.json` is its real throttle text.
- Yahoo screeners (`v1/finance/screener/predefined/saved`) should be re-checked on a weekday; if they return rows,
  they could become MOV's primary source (record a weekday fixture first).
- The fixtures were recorded with a one-off script that is not in the repo. To refresh one, fetch the same URL the
  provider builds and save `{"status", "body"}` (JSON) or `{"status", "content_type", "text"}` (XML/text).

## How to look at the app
Run `.\scripts\dev.ps1`, then open http://localhost:5173. To get a screenshot without the preview pane,
run a small Playwright script against a production build (`npx vite preview --port 4173 --host 127.0.0.1`).
The pattern is in `frontend/e2e/*.spec.ts`. Current look: `docs/screenshot-phase3.png`.
