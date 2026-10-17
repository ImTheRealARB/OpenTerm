# Handoff

_Last updated: 2026-10-19, session 6 (Phases 11-19 on branch `claude/openterm-phases-11-19-a99b2b`; Phase 11 steps 1-5 done except one recording; next: record the OpenRouter stream once the key is set, then step 11.6)._

> **Resuming in a new session or account?** Read "Where things stand" and "Next" below. Try the app with
> `.\scripts\start.ps1`; [docs/COMMANDS.md](docs/COMMANDS.md) lists commands to try.

## Resume here (2026-10-19, end of session 6)
- **Where the work is now:** branch `claude/openterm-phases-11-19-a99b2b`, worktree `.claude/worktrees/openterm-phases-11-19-a99b2b`.
  Session 6 was opened in that worktree, and a hook blocks writes to other worktrees, so its branch was fast-forwarded to
  `claude/openterm-phases-11-19-328938` (`a19f325`, no merge commit) and step 5 was committed on top. The 328938 branch is
  now behind; `git -C <328938 worktree> merge --ff-only claude/openterm-phases-11-19-a99b2b` brings it level if you want to
  continue there. Not merged into `main`; no remote. Nothing is running.
- **Step 5 (LLM gateway) is built except one recording.** The OpenRouter key was not found (not in env, the Windows
  keyring or any `.env`), so `test_recorded_openrouter_stream_gives_tokens_usage_and_cost` stays strict-xfail (`RECORDING`
  marker in `backend/tests/test_phase11.py`).
- **Exact next action:** once `OPENROUTER_API_KEY` is set (APIKEYS panel, or the worktree's `.env`), run from `backend/`
  `uv run python ../scripts/record_llm.py` (picks the first `:free` model, US$0; never prints the key), check the
  fixture has no key in it, delete the `@RECORDING` line and run the gates. Then step 6 closes Phase 11: `THIRD_PARTY.md`,
  the CLAUDE.md rule changes, docs (`ADDING_A_PROVIDER.md` keyed section, `DATA_LIMITS.md`) and the phase verification.
- **The user's working rules for Phases 11-19** (from their prompt; keep following them):
  1. Do one step per turn, in HANDOFF order. A step is a spec, a tests set, or one function's code.
  2. Each phase starts with `docs/specs/PHASE_<n>.md`, with the roadmap's proposed defaults listed at the top for approval.
     Then tests first, then code.
  3. Sonnet subagents only, at most 2 at once, and only for truly parallel pieces. Splitting backend and frontend halves worked well.
  4. Before a step is done, run `uv run pytest -q`, `uv run ruff check .`, `npx tsc --noEmit`, `npx vitest run`,
     `npx playwright test` and `node scripts/bench.mjs`. Record the bench numbers in `docs/PERFORMANCE.md`.
  5. After each step, update only the changed sections of HANDOFF.md and CLAUDE.md, then commit.
  6. At 95% of the 5-hour or weekly limit: stop subagents, write the state to HANDOFF.md, commit, and stop.
  7. Keep output small. If a key is needed, stop and say which one.
- **Before the bench:** port 8000 must be free. The user's own `start.ps1` backend sometimes holds it; ask before stopping it.

## How Phases 6-10 were built (history)
Built in parallel, one git worktree per phase (`openterm-p6..p10`, from `4b3814c`), by Sonnet sessions following
[docs/PARALLEL_BUILD.md](docs/PARALLEL_BUILD.md) (append-only "Phase N" blocks in shared files; only Phase 8 adds
migrations, positions 6-7). Each phase was then merged in order with `git apply --3way`, fully verified (pytest, ruff,
tsc, vitest, all Playwright, bench) and committed with the user's approval:

| Phase | Commit |
|---|---|
| 6 FA, FIL/SEC, OWN, HDS | `96d40b9` |
| 7 FRED, MACRO, RATES, ERN, ECO | `90bffb1` |
| 8 PORT, ALRT (migrations 6-7) | `1070230` |
| 9 EQS, HIST, CORR, COMP, CSV export | `b5515ac`; CSV hook wired into the Phase 6-8 panels in `7e3ca69` |
| 10 SETTINGS, themes, vim, keybinding overrides, Docker, Tauri, release notes | `f0df226` |
| Post-merge fixes + `scripts/start.ps1` | `626bddd` |

All phase worktrees, their `-wip` branches, the backups (`wip-patches/`, `RESUME_PROMPT.md`) and the finished build
sessions are gone; everything is on `main`. Things that still apply from that build:
- Phase 6 SEC fixtures: the user approved their Gmail as the SEC User-Agent **for fixture recording only**; it
  must never be written into the repo. The app reads `SEC_USER_AGENT` from env.
- **Use Sonnet subagents/sessions, not Opus** (user's request: Opus agents used ~55% of the 5-hour window in 15 min).
  Run at most 2-3 at once and check plan usage between steps. When the 5-hour (or weekly) window reaches 90%, stop
  them, write down exactly where each one is, and pause.
- A session started in one worktree cannot write into another (a hook blocks Write/Edit). Work that belongs in
  another worktree goes to a session started there; do not copy files in through a scratchpad.

## Where things stand
- **All 10 phases are built, verified and on `main`** (Phases 1-4 `736d6d5`..`b72466a`, 5 `4b3814c`, 6-10
  `96d40b9`..`f0df226`, then docs and the post-merge fixes). `main` was fast-forwarded on 2026-10-17; the old
  phase worktrees and branches were removed. No git remote. The git identity (ankithrbharadwaj) is set for this repo only.
- The leftover uncommitted Phase 3 copies that sat on `main` were set aside in a stash
  (`main-phase3-leftovers-2026-10-17`); they were identical to `b6dca4e` apart from line endings, so the stash can be dropped.
- Latest verification (`626bddd`, post-merge fixes):
  - Backend: 163 pytest passed (`-n auto`, ~26 s), ruff clean.
  - Frontend: 169 vitest passed, tsc clean, 66 Playwright passed (`--workers=8`, ~29 s).
  - Bench: 16/17 (tick-to-pixel 55-59 ms vs 50 on every run that evening, also with the fixes reverted; see
    `docs/PERFORMANCE.md` "Post-merge fixes"). Phase 10 itself was 17/17 on two of three runs.

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
- 10: done (merged, see Phase 10 details). Backups were deleted.

Remaining:
1. First real Docker build and Tauri build (neither tool is installed on the dev machine). Deferred by the user.
2. Tick-to-pixel bench budget: missed (55-59 ms vs 50) on every run of the post-merge session, including with the
   fixes reverted, so it is machine load or drift, not those fixes; earlier the same day it ran 38-42 ms. Re-run on a
   quiet machine before treating it as a regression.
3. Phases 11-19: plan in [docs/ROADMAP_PHASES_11-19.md](docs/ROADMAP_PHASES_11-19.md) and
   [docs/FEATURE_GAP.md](docs/FEATURE_GAP.md). Work happens in worktree branch `claude/openterm-phases-11-19-328938`
   (fast-forwarded onto the roadmap commit `7d20e69` from `claude/openterm-bloomberg-feature-gap-badb0c`; not on `main` yet).
   Steps (one commit each; a step is a spec, a tests set, or one function's code):

   | Step | State |
   |---|---|
   | 11.1 Spec [docs/specs/PHASE_11.md](docs/specs/PHASE_11.md) | **done**, defaults approved 2026-10-18 |
   | 11.2 Tests set: `backend/tests/test_phase11.py` (39), `frontend/src/net/phase11.test.ts` (5), `frontend/e2e/phase11.spec.ts` (4) | **done**; all marked expected-to-fail per step (see CLAUDE.md) |
   | 11.3 Key store, redaction, `/api/keys`, `KEY REQUIRED`, `APIKEYS` panel | **done** (backend by the main session, frontend by one Sonnet subagent) |
   | 11.4 Job runner, migration 8, `J` frames, `JOBS` panel, bench budgets (JOBS + APIKEYS open) | **done** (backend main session, frontend one Sonnet subagent); bench 21/21 |
   | 11.5 LLM gateway + health | **done except the recording** (main session, no subagents); bench 21/21 on the third run. `test_recorded_openrouter_stream...` waits for the OpenRouter key (`scripts/record_llm.py`) |
   | 11.6 `THIRD_PARTY.md`, CLAUDE.md rule changes, docs, phase verification | pending |

   The tests pin interfaces the spec left open: `keys.KeyStore(env, dotenv, keyring)`, `MemoryKeyring`, `classify()`, `KeyStoreError.kind`
   (`env_locked` 409, `unknown_provider` 404, `bad_request` 400), `redact.redact(text, secrets)`, `Provider.key_name`, `AllFailed.key`,
   `DataError(..., key=)`, `jobs.job_hash`, `jobs.store.JobStore`, sleep params `ignore_cancel` / `fail_at` / `crash_at` / `tag`,
   `llm.sse.parse_sse`, `events_from_payloads`, `llm.spend.check/cost/add/today`, `/api/llm/health`, settings `OPENTERM_KEYRING`
   (`auto|memory|none`), `OPENTERM_DOTENV_PATH`, `OPENTERM_JOB_WORKERS`; frontend `jobFrames.ts` (`parseJobFrame`, `applyJobFrame`,
   `progressText`), `keyRequired.ts`, `functions/apikeysMask.ts` (`maskKey`), `.keyreq` line class.
   Step 3 notes: `backend/openterm/keys.py` (specs, store, `.env` writer, `classify`, `run_test`), `redact.py` (filter on the ring buffer,
   root handlers, httpx/httpcore), `/api/keys*` in `api.py`, router `key_required` (no breaker strike; `AllFailed.key`), 424 in `error()`,
   SOURCES keyed rows from the store (`providers/__init__.py` Phase 11 block). `app.state.on_key_change` re-applies a FRED key set in
   APIKEYS (other keyed adapters arrive in later phases and must read the store the same way). Fixtures: real 401s for Finnhub,
   OpenAI, Anthropic, OpenRouter (`keytest_*_401`); `keytest_openrouter_ok` is doc-shaped. Frontend: `APIKEYS.tsx`, `KeyRequiredLine.tsx`
   (wired into `secPanel` and `macroUi` error lines only; DES, N, GP and others still show their own error text),
   `state/panelContext.ts`, `net/keyRequired.ts`, `apikeysMask.ts`, `apikeysSignup.ts`. Spend cap editing (`C`) waits for step 5.
   Step 4 notes: `backend/openterm/jobs/` (`__init__` = `job_hash` only, kept import-light for workers; `kinds.py` (`sleep` = TEST JOB);
   `worker.py`; `store.py` (migration 8, hash index made on first use, trim 200, results > 8 MB not cached); `runner.py`: own pool of
   spawn workers, two pipes + a shared cancel flag each, one reader thread on pipes + sentinels, hard cancel after 2 s, time limit,
   `WORKER DIED`, 10 frames/s/job). Hub `Client.push` / `Hub.broadcast` carry `J` frames. `/api/jobs` POST/GET, `/{id}` GET/DELETE,
   `DELETE /api/jobs?state=finished`. Frontend: `net/jobFrames.ts`, `net/jobs.ts`, `functions/JOBS.tsx`, `jobsArgs.ts`, status bar `JOBS n`.
   The job budget is split (user's choice): frame-to-paint and server time gated, end to end through the bench proxy is INFO.
   Step 5 notes: `backend/openterm/llm/` = `sse.py` (incremental `SSEParser` + `parse_sse`), `events.py` (`Event`), `openai_compat.py`
   (`OpenAIStream`, tool-call deltas assembled per `index`, emitted on `finish_reason`), `anthropic.py` (`AnthropicStream`, OpenAI-shaped
   messages/tools converted to the Messages API), `spend.py` (`check`/`cost`, per-day spend in `kv` `llm_spend:<date>` added in one SQL
   statement, cap in `kv` `llm_cap`, default US$1), `client.py` (`Gateway.chat(messages, model, provider="openrouter", tools,
   max_tokens, temperature)`: KEY REQUIRED / PRICE UNKNOWN / SPEND CAP REACHED before any network call, OpenRouter prices from its
   `/models` list (cached 1 h, `:free` = 0), OpenAI/Anthropic prices from `config.yaml` `llm.prices` (left empty on purpose), worst case
   charged if a stream ends without usage; `health()`, Ollama probe 300 ms cached 10 s). API: `GET /api/llm/health`,
   `PUT /api/llm/cap` (loopback, 0-1000), `/api/keys` `spend` is real, SOURCES has an `ollama` row. The gateway is built on first use
   (`api.llm_of`; `app.state.llm` reset in the lifespan). Fixture mode: Ollama port refuses, OpenRouter chat replays
   `llm_openrouter_stream.txt` if present, other LLM hosts 404. No AI function calls `chat()` yet (Phase 16). Frontend: APIKEYS `C`
   edits the cap (`functions/spendCap.ts`). The `client` fixture now clears every KEY_SPECS env var.
   Baseline before Phase 11 code: 163 pytest, 169 vitest, 66 Playwright, bench 17/17 on the rerun (see `docs/PERFORMANCE.md`
   "Phase 11 baseline"). Open problem: port 8000 was held by the user's own `start.ps1` backend (system Python); stop it
   (with the user's OK) before the bench.

Done after the merge: `main` fast-forwarded; panel tab names the security only for functions that use it; charts skip
the volume histogram when a series has no volume (FRED's flat line); `scripts/start.ps1` / `scripts/start` run the
built app from the backend on :8000 and open the browser.

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
- `Dockerfile`/`docker-compose.yml` and the Tauri scaffold (`desktop/`) have never been built (no Docker or Rust here).
- The 50k-bar chart-pan bench budget misses occasionally (about one run in three); the other 16 budgets are stable.
- The fixtures were recorded with a one-off script that is not in the repo. To refresh one, fetch the same URL the
  provider builds and save `{"status", "body"}` (JSON) or `{"status", "content_type", "text"}` (XML/text).

## How to look at the app
To use it: `.\scripts\start.ps1` (builds if needed, serves on http://localhost:8000, opens the browser).
To develop: `.\scripts\dev.ps1`, then open http://localhost:5173 (hot reload). For a no-network demo with recorded data, set
`$env:OPENTERM_FIXTURES = '1'` before starting the backend. For `FA`/`FIL`/`OWN` against live SEC data, set
`$env:SEC_USER_AGENT = 'Your Name you@example.com'` first. To get a screenshot without the preview pane,
run a small Playwright script against a production build (`npx vite preview --port 4173 --host 127.0.0.1`).
The pattern is in `frontend/e2e/*.spec.ts`. Current look: `docs/screenshot-phase3.png`.
