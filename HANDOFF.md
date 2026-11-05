# Handoff

_Last updated: 2026-11-05 (local gate + bench of NEXT_FEATURES: ALL PASS, bench 37/37). `main` has Phases 1-17 and 19, GUI mode, the strategy editor, GUI_SIMPLE_AND_BUGS and NEXT_FEATURES (PR #1 merged 2026-11-05, merge commit `d8ee11f`). Phase 18 stays paused._

> **Resuming in a new session or account?** Read "Resume here", "Where things stand" and "Next" below. Try the app with
> `.\scripts\start.ps1`; [docs/COMMANDS.md](docs/COMMANDS.md) lists commands to try, [docs/FUNCTIONS.md](docs/FUNCTIONS.md) every function.

## Kite follow-ups (2026-11-05, branch `claude/kite-followups-372029`, committed, NOT pushed)
Done, against the live paid session (market open): every segment (NSE, BSE, NFO future + weekly option, BFO, MCX, CDS, indices, 20Y daily bars) answers; the ticker streams NSE / BSE / NFO / MCX / CDS through the hub. Fixed what the live run found: BSE scrip codes
(`500325.BO`), all-zero `oi` on cash bars, untraded-contract time and zero OHLC, `k` tick source had no frontend label (now `RT KITE`), `KiteTicker.covers` let Yahoo's delayed ticks through when an option was quiet. The Kite login-expired note now shows on Q, DES and HIST too
(`rowsFallbackText` / `fallbackText`; HIST text changed to `<SRC> DOWN, VIA FALLBACK`, the phase9 e2e follows). Real recordings replace most doc-shaped fixtures (`scripts/record_kite_live.py`; list in `docs/DATA_SOURCES.md`); tests in `backend/tests/test_kite_live_followups.py`,
`frontend/e2e/kite-fallback.spec.ts`. The read-only scan test still passes.
- **Next:** OMON / CT for `.BFO` (SENSEX options) and `.CDS` (`derivative_root` knows only NFO / MCX; spot logic differs: BSE:SENSEX for BFO, no spot for CDS); `1D` on Kite is 48 hours, not one session; the option-chain fixtures are still doc-shaped (invented NIFTY 25000 layout).
- **Not verified:** a full login-expiry cycle live (06:00 IST tomorrow); the ticker was checked for ~1 minute in total, not across a reconnect (the reconnect path is unchanged, tested only by the existing backoff code).

## Kite market data (2026-11-05, same branch, NOT committed)
Kite is a `quotes` + `history` provider ranked #1 for Indian symbols; expired login falls back to Yahoo and shows `KITE LOGIN EXPIRED` (GP, via `fallback_notes` and `functions/fallbackText.ts`). Measured live: quote 52 ms vs Yahoo 341 ms, 5 min 1M history 125 vs 216 ms, minute depth back to 2015. Real fixtures recorded (quote, 5 min bars). Numbers and caveats in `docs/DATA_SOURCES.md`. (The follow-ups above finished the ticker re-check, the F&O / MCX / CDS live tests and the Q / DES / HIST note.)

## Upstox removed (2026-11-05, same branch, NOT committed)
Decision: the owner cannot get an Upstox token and will pay for Kite instead, so the adapter and every reference are gone (`providers/upstox*.py`, its `Rank` entries, `KeySpec`/key test, `main.py` wiring, `service.py` cache tag, `test_upstox.py`, README/docs rows). Kept: hierarchy, per-source candle limits, Yahoo as fallback for `.NS`/`.BO`. Kite is NOT added to the quotes hierarchy yet (later, once he has a key). Tests that used Upstox as a stand-in now use fake providers.

## Batch 2 + handoff (2026-11-05, branch `claude/ports-and-official-stats`, stacked on PR #14, NOT committed)
Built: `PORTS` (PortWatch port activity: bare = 25 busiest ports; `PORTS <words>` = ports matching name/country) and `DBSRCH` (search DBnomics, which mirrors OECD, Eurostat, BIS,
IMF, ECB and more; Enter drills dataset -> series -> `ECST DBN:...` chart). The planned separate OECD/Eurostat/BIS/IMF adapters were DROPPED on purpose: DBnomics already serves them through
`ECST DBN:<provider>/<dataset>/<series>`; the gap was discovery, which DBSRCH fills. The series-id regex now allows `@` (OECD ids such as `DSD_TAXBEN_NRR@DF_NRR`).
- **Gates (this branch, 2026-11-05):** ruff, tsc, vitest, pytest all pass; bench 37/37 (a lone "Job J frame to paint 54 ms vs 50" miss appeared twice, then 35.5 ms after a 45 s rest: noise);
  e2e 296 pass, 2 fail: (1) `gui-panels.spec.ts` SETTINGS "INTERFACE MODE row" (predates all of this work, fails alone, step count off after the font rows), (2) `phase12.spec.ts` BT EDIT "server's reason for refusing code" (flaky, passes alone).
- **Browser-checked on recorded data:** SHIP, PORTS, DBSRCH render; USMAC/UKCO/ADDR show KEY REQUIRED without keys.
- **Caveats:** PORTS first (uncached) query takes 12-33 s on the live service (45 s timeout); PORTS import/export units are assumed metric tons (the layer does not say; the panel notes it);
  `shipping.FLAKY_MESSAGES` now has 3 entries ("Invalid query parameters" added because it is a third face of the ArcGIS node glitch); startup bundle 123.3 KB gz (CLAUDE.md said 119.5; cause not found).
- **Not done / next, in order:** (1) merge PR #14 (Upstox is being removed, so no live test is needed); (2) commit + PR for this branch (user said commit only when asked);
  (3) live-test Comtrade, BLS, BEA, Census, Companies House, Marketaux, Etherscan keys (fixtures are doc-shaped, several field names from memory); (4) AISstream (free key, beta WebSocket, biggest piece);
  (5) fix the SETTINGS e2e step count (separate tiny PR); (6) find the +3.5 KB startup bundle growth; (7) smaller extras listed in `docs/DATA_SOURCES.md`.

## Data-source batch (2026-11-05, branch `claude/source-hierarchy-upstox`, NOT committed)
State: source hierarchy + per-source candle limits (earlier), plus this batch: `SHIP` (PortWatch, real recording), `TRADE` (Comtrade),
`USMAC` (BLS/BEA/Census), `UKCO` (Companies House), `ADDR` (Etherscan), Frankfurter (FX history/quotes behind Yahoo), Marketaux (news sentiment).
- **Verified against real services:** PortWatch (recorded), Frankfurter v2 rates, Etherscan's bad-key answer. **Doc-shaped, never run with a key:**
  Comtrade, BLS, BEA, Census, Companies House, Marketaux, Etherscan (fixtures `*_docshape_*`, invented numbers). Several field names are from memory
  (BEA NIPA/ITA/GDPbyIndustry fields, Comtrade response fields, Census query forms): a wrong guess shows as an `ERR` line, not wrong numbers.
  First live test per key: paste it in APIKEYS, TEST, open the panel.
- **Gates:** pytest 1897, vitest 1078, tsc + ruff clean, bench 37/37 PASS, e2e 297 passed + 1 failed: `gui-panels.spec.ts` "SETTINGS panel: the INTERFACE MODE row" (presses j 14 times but lands on the `font` row; SETTINGS code and the spec are unchanged by this branch, so it predates it, probably from the font-row work in 1c84020). Not fixed here.
- **Next:** commit + PR when the user says so; AISstream; PortWatch ports; OECD/Eurostat/BIS/IMF; live-test each key. Not reviewed in a browser yet.

## Update 2026-11-05 (branch `claude/settings-e2e-bundle-1d20f4`, not committed)
- **e2e fix:** `gui-panels.spec.ts` "SETTINGS panel: the INTERFACE MODE row" pressed `j` a fixed 14 times, which landed on `font` after the font rows were
  added. It now presses `j` until the cursor row is `mode` (cap 40). Passes alone. NOTE: Playwright's preview proxies `/api` to a hard-coded :8000, and this test
  changes the mode setting, which syncs back with a PUT: with a live `python -m openterm` up, run it against a scratch vite config whose preview proxy points
  at an unused port, or you overwrite that instance's saved settings.
- **Startup bundle FIX applied (not committed):** `components/Panel.tsx` now renders `gui/LazyPanelToolbar.tsx` (own chunk `PanelToolbar-*.js`, 1.7 KB gz; empty `.pt` placeholder
  keeps the height until it loads). Startup `index-*.js`: 122.20 -> 117.08 KB gz on this base (`vite build`). Checked: tsc, vitest `src/gui`, e2e gui-panels + beginner + gui-tabs (26 pass).
  Gotcha hit: `useState(fn)` calls `fn` as a lazy initializer, so a stored component needs `useState(() => fn)`. The branch `claude/ports-and-official-stats` gets the fix when merged
  (it touches `PanelToolbar.tsx` and `gpArgs.ts`, not `Panel.tsx`'s import line, so expect no conflict). Full gate and bench not run.
- **Startup bundle investigation (the analysis behind it).** Vite-reported gzip of `index-*.js` per commit: `fb87fcb` 117.99 ->
  `8cdedf2` 118.01 -> `4df76e1` 120.86 (+2.85, GUI tabs/dropdown commit) -> `2cf50aa` 120.97 -> `1380720` 121.28 (custom font) -> `1c84020` 122.21
  (font presets, +0.9) -> `a0fc2d4` (= `main`) 122.20 -> `738a397` (`claude/ports-and-official-stats`) 123.03 (+0.83: registry entries for the 5 new
  functions +1.7 KB raw, `net/api.ts` +0.75 KB raw, `useHistoryLimits.ts` +0.44 KB raw). The "119.5" in CLAUDE.md does not match this build's number for the
  same era (`fb87fcb` reads 118.0 here), so compare only within one measurement method; the growth since is real (+4.2 KB on main, +0.8 on the branch).
  **Main culprit:** `gui/PanelToolbar.tsx` is a static import of `components/Panel.tsx`, so the GUI toolbar and everything it imports sit in the startup chunk:
  `functions/gpArgs.ts` (4.3 KB raw, +1.2 later), `chart/indicators.ts` (2.9 KB raw: the INDICATORS list), `chart/chartTypes.ts`, `gui/TabStrip.tsx` 1.8, `gui/sidebarState.ts`,
  `gui/tabsState.ts`. Cheapest fix: load `PanelToolbar` through a lazy piece (`LazyGui` pattern, but it needs props `id fn args symbol`, so a prop-passing variant;
  reserve the toolbar height so the panel does not jump) ~ -2.9 KB gz. Smaller option: give `gpArgs.ts` its own list of indicator names so it stops pulling
  `indicators.ts` (~ -1 KB gz). Font presets (`fontPresets.ts` 2 KB raw) are needed at startup (`settings/font.ts`), leave them.

## Resume here (cloud session 2026-11-04 + local gate 2026-11-05; MERGED to `main` via https://github.com/ImTheRealARB/OpenTerm/pull/1, `d8ee11f`)
`docs/specs/GUI_SIMPLE_AND_BUGS.md` Parts 0-5 are DONE and merged to `main` (2026-11-05). Cloud gate: ALL PASS
(pytest 1726, vitest 586, e2e 245). Bench vs the cloud baseline: `docs/PERFORMANCE.md` "Cloud session end 2026-11-04". Commits labelled WIP are
unreviewed checkpoints; the reviewed step commit follows each one.
- **Part 0:** cloud baseline (`docs/PERFORMANCE.md` "Cloud baseline 2026-11-04").
- **Part 1 (beginner GUI):** `frontend/e2e/beginner.spec.ts` = 10 mouse-only tasks, all pass in <= 4 clicks with no function code typed
  (before: 4 possible by mouse, 6 impossible; brief `docs/review/cloud/BEGINNER_CLICKS.md`). Built: company-name search (`gui/companySearch.ts`, `useCompanies.ts`;
  screener universe + `/api/search`), sidebar "Start here", glossary (`gui/glossary.ts`, `glossaryTip.ts`, `data-term`), `PanelNote` `plain`/`actions`/`onRetry`,
  empty states with "Add a stock"/"Add an alert" (`gui/askBus.ts`), BT starter templates (`functions/BtStarter.tsx`), starter layout for new GUI users
  (`gui/starterLayout.ts`), `KeyNeeded` with "Open API keys", BT editor fills its panel, live keybindings in tour/help (`gui/purposes.ts`), FA GUI look,
  fresh-eyes critique fixes (`docs/review/cloud/GUI_CRITIQUE.md`, incl. `functions/QuoteErrors.tsx`, `alertPlain.ts`). Notes: `BUILD_1B_A.md`, `BUILD_1B_B.md`.
- **Part 2 (known bugs):** all fixed with tests (`docs/review/cloud/BACKEND_BUGS.md`, `FRONTEND_BUGS.md`; DONE marks in `docs/review/DECISIONS_FOR_USER.md`).
- **Part 3 (audit):** `docs/review/cloud/AUDIT.md`: 0 high, 3 medium (all confirmed and fixed: SEAS exchange-local dates, alert trigger retry, Yahoo real granularity), 9 low deferred in DECISIONS_FOR_USER.md.
- **Part 4 (Terminal conventions):** sector words after the ticker (`command/sectors.ts`), digits + Enter opens a grid row (`keys/numberSelect.ts`), F2/F3/F4/F8/F9 (+Shift+F9) sector keys,
  Alt+Backspace back, `FUNC` directory (aliases MENU, DIR), aliases WCRS->FXC, MOST->MOV, PRTU->PORT. `docs/review/cloud/PART4.md`.
- **Never verified:** the GUI on a real (non-fixture) Yahoo session; Retry is wired on DES, GP and quote grids only; number-select does not cover DOM lists; the GUI-mode collapsed top command line relies on Ctrl+K (covered by gui-shell e2e).
- **Decisions left to the user:** the four "confirm or revert" items and the DLVR `DESKTOP` toggle (DECISIONS_FOR_USER.md, untouched); the 9 low audit items;
  startup bundle is 125.8 KB gz (+5.8 KB: GUI +4.2 within its 5 KB cap, Part 4 +1.6 KB); NSE holidays cover fixed dates + Good Friday only (festivals not computable by rule; the UI says so).
- **Performance pass (after Parts 0-5):** data-oriented rewrite of the tick path, SEAS and BT open (user's method; `docs/PERFORMANCE.md` "Performance pass 2026-11-04"): bench 37/37 then 36/37 (lone Job J frame miss). Then bundle 124.8 -> 119.5 KB gz (under main's 120.0) and an allocation-free SEAS core: bench 37/37, then 35/37 (chart-pan lone miss; SEAS swings 10-17 ms run to run). Gate ALL PASS apart from load-only timing vitests (pass alone).
- **NEXT_FEATURES job (`docs/specs/NEXT_FEATURES.md`): ALL 6 STEPS BUILT AND LOCALLY GATED (2026-11-05, Windows laptop).** Gate ALL PASS with
  `--e2e-last`: pytest 1776, vitest 1020, e2e 297. Bench 37/37, 36/37 (chart pan 33.4 ms once), 37/37; bundle 119.9 KB gz. `docs/PERFORMANCE.md`
  "Local gate after NEXT_FEATURES". Fixed in that session (tests first): GP pan/zoom lost presses inside one frame (`ChartView` `pendingRange`;
  pre-existing on main, exposed by `gp-toggle` on a fast machine), BT EDIT 80 ms focus retry stole focus after Esc (`BtEditor` `leftBox`; new
  phase12 test with a paused clock), "under 50 dollars" ignored by the EQS English parser (`eqsNatural.readNumber`). Manual smoke (fixtures, GUI +
  Terminal) passed for every item in the local prompt; Shift+T and `+` could not be sent by the in-app browser tool (covered by e2e).
  Fully parallel gates failed 1-2 random e2e tests per run on this laptop (each passes alone), so `gates.mjs` now runs e2e after pytest + vitest by
  default (`--parallel` = old mode). Open: the `eqsFilter` timing vitest still fails under load (passes alone).
  - Step 1 NL commands: `command/natural.ts` (pure, 78-row table), `nlRun.ts` (`needsNatural`, sync, in entry), `nlResolve.ts` + `nlRoute.ts` + `cmdExtras.tsx` (lazy),
    syntax hint `command/syntaxHint.ts` (`data-testid=syntax-hint`). Routing: exact codes > compare (`compareNatural.ts`) > screener (`EQS <text>`, `functions/eqsNatural.ts`)
    > company + intent > none. GUI sidebar search / SymbolPicker go through `gui/runTyped.ts`. Ambiguity rule: top company group must have >= 10x the next group's market cap, else DID YOU MEAN.
  - Step 2 grid header glossary: `components/gridHeaderHit.ts`, `gui/gridTips.ts`; hover in GUI mode, **Shift+T** cycles (`?` is the global cheat sheet).
  - Step 3 indicator toggles keep zoom: `chart/indicatorDiff.ts`; gauges `chart.rebuilds/panes/visFrom/visTo`. A typed Terminal re-run still remounts (Panel keys on `panel.pos`); a split also remounts.
  - Step 4 library: `chart/library/` (109 indicators, catalog + known-value tests written from formula definitions, no ported code), `chart/formula.ts` (no eval), `chart/libraryWorker.ts`
    wired in `indicators.worker.ts`; panel `IND`; presets `/api/indicator-presets` (kv `ind_presets`, `indicator_presets.py`, `net/presetsApi.ts`). GP args `ATR(14)`, `LIB:CMF`, `F:<urlencoded formula>`.
  - Step 5 BT sentence builder: `functions/ruleSentence.ts` (+ shared `ruleSentence.cases.json`, also checked by backend `test_rule_sentence_cases.py`), `BtRuleBuilder.tsx` (lazy, GUI only).
    The grammar is one boolean (long while true), so "sell when" is derived text, not a second rule.
  - Step 6: `TMPL` templates (`gui/templates.ts`; Settings menu in GUI), EQS English args (P/E, dividend yield, beta are NOT in the screener payload: shown as ignored),
    compare, alert from the chart (`A` key, Shift+A / toolbar arms a click, Alt+click; `command/priceAlert.ts`, `chart/alertPrice.ts`, dashed ALRT price lines, gauge `chart.alertLines`).
  - **Lazy vim risk: checked, no problem** (`e2e/phase10.spec.ts` 6/6 locally). The builders' unidentified vitest flake is the `eqsFilter`
    "10k rows well inside a frame" timing test (fails only under the parallel gate). `playwright.config.ts` now honours `PW_PORT`.
  - WIP-labelled commits on the branch are unreviewed checkpoints; the final state is the branch tip.
- **Next:** optional real-data (non-fixture) screenshot pass of the GUI; items in DECISIONS_FOR_USER.md (four confirm-or-revert items, DLVR `DESKTOP` toggle, 9 low audit items);
  open: IND opened from the GP toolbar splits the panel and the chart remounts (zoom resets); the `eqsFilter` timing vitest fails under load.

## GUI top-bar command line (2026-11-05, branch `claude/exciting-darwin-847c96`)
## GUI polish session (2026-11-05, MERGED to `main` via PRs #2-#4)
Open next: add e2e for tabs, sidebar toggle, gp-interval and gp-type (none exist; full e2e and bench NOT run after these changes, `openApp` seeds tabs OFF); keep hidden tabs mounted (switching a tab remounts the panel, so chart zoom resets).
- Removed the `gui.css` rule that collapsed the top-bar command line to a 2px sliver in GUI mode (beginner item 15). It is now always visible beside the sidebar search box. Not run through e2e/bench; CSS-only, uncommitted.

- Sidebar toggle (2026-11-05, MERGED): a "Sidebar" button at the left of the GUI menu bar shows/hides the left sidebar (`gui/sidebarState.ts`, remembered in localStorage `openterm.sidebarHidden`, default shown). `Sidebar` is now a wrapper that mounts `SidebarPanel` only while shown. Checked by hand in the browser; no e2e test yet (add one to `beginner.spec.ts` if kept).
- Chart blank-left fix (2026-11-05, MERGED): `ChartView` timeScale now sets `lockVisibleTimeRangeOnResize: true`, so a chart that gets wider (panel maximized, sibling closed, window resized) rescales its bars instead of leaving empty space on the left. Checked by hand (shrink then widen); no e2e test.
- GP candle-length dropdown (2026-11-05, MERGED): a `<select>` after the GP toolbar buttons (`gui/PanelToolbar.tsx`, `data-testid=gp-interval`; choices in `functions/gpArgs.ts` `INTERVAL_CHOICES`, `withInterval` has vitest). It rewrites the panel args like typing `GP 5D 15MIN`; the range buttons (keys 1-8) keep the chosen candle length (changed 2026-11-05; they used to reset it to Auto), so e.g. 5 min then 1Y shows Yahoo's "only available for the last N days" error until the user picks a longer candle or Auto. Follow-up (same day): the dropdown now shows each limit and disables lengths the range cannot use, and the error note has "Use Auto candles" / "Show <longest range> instead" buttons (`intervalFits`, `longestRangeFor`, `intervalLimitText` in `gpArgs.ts`, vitest added). Not looked at in a browser yet. Choosing a minute interval on a long range (e.g. 1Y + 15 min) shows Yahoo's "only available for the last N days" error. Checked by hand (5D + 5 min); no e2e test.
- Source hierarchy (Upstox part REMOVED, see top) (2026-11-05, branch `claude/source-hierarchy-upstox`, NOT committed or merged): (1) `providers/hierarchy.py` = the ranked source table for `quotes` and `history` with the reasons (depth, freshness, rate limits) beside each entry; `config.yaml` no longer pins those two; SOURCES rows carry `hierarchy`. (2) Intraday depth moved from `ranges.normalize` into each provider (`intraday_days`, new `ProviderError` kind `depth`); `GET /api/history/limits?symbol=X`; the GUI candle dropdown and clash note read it (the copied limit table in `gpArgs.ts` is gone). (3) `providers/upstox.py` (free Analytics Token, real-time NSE/BSE quotes, minute candles from 2022), key in APIKEYS, ranked above Yahoo for `.NS`/`.BO`/`^NSEI`/`^NSEBANK`/`^BSESN`. (4) `docs/DATA_SOURCES.md` = how ranking works + the free-source shortlist. Gates run: pytest 1815 passed, ruff clean, tsc clean, vitest 1046 passed (all 98 files); checked in a browser against a fixture-mode backend with a fake token (limits, 400 message, fallback line). NOT run: e2e, bench. **Next:** run the whole gate + bench (`node scripts/gates.mjs`, `node scripts/bench.mjs`; the hierarchy adds one dict lookup per router call), test Upstox with a real token (APIKEYS test button, then `GP RELIANCE.NS` 5 min 1Y), re-record fixtures if shapes differ, then Angel One / Tiingo per `docs/DATA_SOURCES.md`. Known gap: `/api/history/limits` is optimistic while a top source is failing (the error then says PROVIDER DOWN).
- GUI tabs + chart types (2026-11-05, MERGED): (1) GUI mode now shows panels as browser-style tabs by default (`gui/TabStrip.tsx`, `gui/tabsState.ts`, localStorage `openterm.guiTabs`, "0" = tiles; menu-bar "Tiles/Tabs" button; `components/Workspace.tsx` renders only the focused panel, keyed by id so each tab remounts; "+" = `split("v")`, so the 9-panel cap applies; Max button hidden in tabs). Terminal mode is untouched. `e2e/app.ts` `openApp` seeds tabs OFF unless `tabs: true`, so existing GUI specs still see tiles. (2) Chart types: CANDLE, HOLLOW, OHLC (Bars), LINE, AREA, BASELINE, HEIKIN (`chart/chartTypes.ts`, `chart/heikin.ts` + test; `settings/schema.ts` list extended; GUI dropdown `data-testid=gp-type` replaces the "Type" button; the C key still cycles). Heikin Ashi ignores live ticks until the next history load. Checked by hand in the browser; vitest 1025 pass; e2e NOT run (port 8000 is the user's running backend). Next: add an e2e for tabs, run the beginner suite.
- Tab strip moved above the command line (2026-11-05, MERGED): `TabStrip` now renders in `App.tsx` before `TopBar` (extra top grid row via `.app.has-tabs`; do NOT name that class `tabs`, `styles.css` already has a flex `.tabs`). `Workspace.tsx` just renders the focused panel. Checked by hand.
- README overhaul + retaken screenshots (2026-11-05, MERGED to `main` via PR #8): `README.md` rewritten (logo header and badges, hero screenshot, quick start per OS, features table, full-width screenshots, speed table unchanged and matching `docs/PERFORMANCE.md` 2026-11-05, install blocks for Windows / macOS / Linux (apt via nvm, dnf, pacman), optional-keys table, per-OS troubleshooting). New `scripts/screenshots.mjs` (see CLAUDE.md "Public repo") retook 9 shots with live data at 1440x810 CSS px; the hero is GUI mode with the sidebar hidden (with it, the quote grid's CHG column is clipped). `scripts/install-launcher` was not executable in git (mode 100644), fixed with `git update-index --chmod=+x` so `./scripts/install-launcher` works on macOS/Linux. Not done: the macOS/Linux scripts have still never been run by anyone; hero shows some `STALE` quote rows because US markets were closed when shot (retake while open); `gui-first-screen.png` and other old `gui-*.png` are now unreferenced (left in place). Next: user reviews README on GitHub, then push/merge.
- Status bar off by default in GUI + logo + no 1 min candle (2026-11-05, MERGED via PR #6; the Status toggle later moved into the Settings menu, see the font entry): (1) `gui/statusBarState.ts` (localStorage `openterm.statusBarShown`, default hidden); `App.tsx` renders `StatusBar` only in terminal mode or when shown; menu-bar "Status" button (`data-testid=statusbar-toggle`). The Terminal/GUI `ModeToggle` lives inside the status bar, so it hides too (Alt+G and Settings > Terminal still switch). `openApp` seeds it ON unless `statusBar: false`; new e2e in `gui-shell.spec.ts`. The alert flash (`ALRT n`) is also hidden with the bar. (2) "1 min" removed from `INTERVAL_CHOICES` (dropdown only; `GP 5D 1MIN` still works). (3) `frontend/public/logo.svg` (window + `OT>_`, amber on black, user's design) is the tab icon via `index.html`; not used elsewhere yet, no small-size (32px) variant. Checks: tsc clean, gui-shell + beginner e2e 21/22 pass; `default openApp is the terminal shell` fails on this branch with or without the change (not investigated). Full gates and bench NOT run.
- **STATE AFTER THE 2026-11-05 SESSION (read this first, then the entries below):** everything below is on `main` (PRs #6, #8, #9, #10, #11; #7 is a redundant open PR, safe to close). Final shape: the GUI bottom status bar is hidden by default (Settings menu > "VIEW" row toggles it; Terminal mode always shows it); the font is chosen from the Settings menu "FONT" dropdown, the SETTINGS panel FONT row (H/L) or `SETTINGS FONT NEXT|PREV|<name>`, with NO install check and NO font messages from the dropdown (a canvas check gave false warnings and was removed); presets are JetBrains Mono (default), GitHub Mono, Geist Mono, Fira Code, Mononoki, Hack, Monaco, DejaVu Sans Mono, Menlo, Consolas, Comic Sans (Bergoom was tried and removed); the chart candle dropdown has no "1 min"; README rewritten with per-OS install and larger live screenshots (`scripts/screenshots.mjs`); tab icon = `frontend/public/logo.svg`.
  **Open items:** (1) `e2e/gui-shell.spec.ts` "default openApp is the terminal shell" fails (page starts in GUI) with and without these changes, not investigated; (2) backend `settings_store.CHART_TYPES` lacks HOLLOW/BASELINE/HEIKIN that the frontend offers, so saving them as the default chart type is probably rejected by `PUT /api/settings` (fix: add them in the backend and its test); (3) full gates, e2e and bench were NOT run after these changes (fonts add about 0.6 MB of lazy files, check the startup budget); (4) macOS/Linux install steps in the README were written from the scripts and never run; (5) the alert flash `ALRT n` is hidden with the status bar in GUI mode; (6) a proportional font misaligns the DOM tables (monospace recommended); (7) Docker/Tauri still never built.
- Font presets (2026-11-05, MERGED via PRs #10 and #11; the "UNCOMMITTED" wording below is history; replaces the "installed fonts only" idea below): 12 presets in `settings/fontPresets.ts` (JetBrains Mono default, GitHub Mono stack, Geist Mono, Fira Code, Mononoki, Hack, Monaco, DejaVu Sans Mono, Menlo, Consolas, Comic Sans). Six are BUNDLED (woff2 in `frontend/public/fonts`, about 0.6 MB total, licences in `public/fonts/licenses` and THIRD_PARTY.md, `@font-face` in `src/fonts.css` with `local()` first and `font-display: swap`, so only the font in use downloads and startup is not blocked). Monaco/Menlo/Consolas/Comic Sans are system-only (fall back to the default font if the computer lacks them; no warning, the user asked for none). Switch: menu-bar dropdown `data-testid=font-select` (GUI), SETTINGS FONT row (H/L), `SETTINGS FONT NEXT|PREV|<name>`; any other installed name still works. `runtime.ts` bumps `displayVersion` on `document.fonts` `loadingdone` so canvases redraw after a lazy load. Checked in Playwright: all presets switch in 6-107 ms, files 200, PUT 200, startup requests no font file when JetBrains Mono is installed. Not checked: bench (startup budgets), e2e, Mac/Linux. DejaVu and Hack are the biggest (about 105-140 KB per weight) but lazy. Bergoom (Bloomberg-style) was tried and removed at the user's request (looked bad, proportional).
- Custom font setting (2026-11-05, MERGED via PRs #8 and #9, superseded by the presets above): `SETTINGS FONT <installed font name>|DEFAULT` and a "FONT" row in the SETTINGS panel (Enter prefills the command). New `settings/font.ts` (name rule + `--font-user` apply, pure), (a canvas "is it installed" check was tried and removed: it gave false warnings), `Settings.font` in `schema.ts` (default ""), applied in `runtime.ts` (bumps `displayVersion` so canvas grids/charts redraw), backend `settings_store.py` `font` field (unknown fields are rejected, so it was required). `styles.css`: `--font-base` is the old stack, `--font = var(--font-user, var(--font-base))`. System-installed fonts only (no web fonts, speed rule). Checked: tsc, vitest `src/settings`, pytest `-k settings`, and a Playwright run on a throwaway server (applies, rejects a missing font, resets, PUT 200, survives reload). NOT checked by eye: canvas grids/charts with a proportional font (columns may misalign; monospace recommended). No e2e spec added. Found, not fixed: backend `settings_store.CHART_TYPES` lacks HOLLOW/BASELINE/HEIKIN that the frontend allows, so saving those as the default chart type is likely rejected by `PUT /api/settings`.
- AAPL 1D chart check (2026-11-05): `/api/history?range=1D` returns the full 09:30-16:00 ET session (79 bars) and GP fits it; "10:00" is only the first axis label.

## Resume here (updated 2026-11-03)
**Current state in one place:** `origin/main` = `96ed188` plus this docs commit. Everything in `docs/specs/NEXT_SESSION.md` is done and on `main`: GUI mode (Part 1),
Phase 17 MCP server / alert delivery / daily brief (Part 2), strategy editor (Part 3). Phases 1-17 and 19 are built; **Phase 18 (brokers/orders) stays PAUSED.**
Last full gate: pytest 1708, e2e 226 (ALL PASS). Bench on this busy machine scores 29-36 of 37, the same as the base commits under the same load (`docs/PERFORMANCE.md`).
- **More AI providers (2026-11-03, committed in `34533a1`, on `main`):** APIKEYS and the AI gateway now also take `opencodego`, `deepseek`, `groq`, `mistral`, `xai`, `together`, `fireworks`, `gemini`
  (all OpenAI-compatible; base URLs in `llm/openai_compat.BASES`, key specs and key tests in `keys.py`). Not run against real keys. Models need a price in `config.yaml llm.prices` while a spend cap is set.
- **Run it:** `openterm` in PowerShell (installed at `C:\Users\Asus\.local\bin\openterm.cmd`; runs `scripts/start.ps1` of the main checkout `C:\Users\Asus\Documents\OpenTerm`).
  That checkout must be on the latest `main` (`git pull`); its uncommitted CLAUDE.md block "Imported from AGENTS.md" is the user's own and was kept.
  Since 2026-11-03 `start.ps1` / `start` run `npm ci` when `package-lock.json` changed (a pull that added CodeMirror broke `openterm` before; tested on port 8011: install, build, start; second start skips it).
- **Never verified for real:** SMTP / Telegram / webhook delivery with real credentials; Claude Desktop connecting to the MCP bridge; a 37/37 bench on a quiet machine; Docker and Tauri builds; macOS/Linux scripts.
- **Decisions left to the user:** whether the DLVR `DESKTOP` toggle should gate desktop notifications (today they fire whenever the browser allows); whether the BT editor should fill the panel (fixed 22em now).
- **Next job (2026-11-04):** `docs/specs/GUI_SIMPLE_AND_BUGS.md` is the cloud-session super prompt (Opus orchestrating, at most 2 Sonnet subagents): beginner-simple GUI
  measured by a 10-task click-count e2e suite, every known bug, one audit pass, then Terminal mode closer to classic terminal workflow (conventions only, no trade dress). Not started.
- **Ideas for next:** plain-English rule builder for GUI mode (deferred in NEXT_SESSION.md); items in `docs/review/DECISIONS_FOR_USER.md`; Phase 18 only if the user unpauses it.

### Entries per part (newest first)
- **Strategy editor (NEXT_SESSION.md Part 3): DONE, uncommitted (2026-11-03, branch `claude/strategy-editor-part-3-588d90`, fast-forwarded onto the Phase 17 commit `20b5bd0`).**
  `BT EDIT` is CodeMirror 6 (`frontend/src/bt/codeEditor.ts`, reached only by a dynamic `import()` in `BtEditor.tsx`: own 126 KB gz chunk, startup bundle unchanged 119.9 KB).
  Templates in `backend/openterm/bt/templates.py` (`GET /api/bt/templates`); a new name opens the template list, `T` after Esc reopens it (GUI toolbar button too). Live check
  `POST /api/bt/check` (sandbox only, nothing saved) 0.4 s after typing; `bt/sandboxError.ts` parses `LINE n:`; error shows under the line (`.cm-sbx-msg`) and as `SANDBOX:` text.
  Gate ALL PASS (pytest 1708, e2e 226; the first gate run had 2 BT e2e flakes "failed to fetch dynamically imported module", spec alone 23/23, rerun green).
  Bench 35/37, then 29/37 under heavier load; baseline `20b5bd0` in `C:\otbase` scored 36/37 and 29/37 alternated with it (`docs/PERFORMANCE.md` "Strategy editor bench").
  Real-backend smoke (fixture server + built frontend): templates load, RSI template opens, `import os` marked on line 1, Ctrl+K reaches the command line.
  **Pushed to `origin/main` (fast-forward to `96ed188`, includes GUI mode and Phase 17).** The main checkout's local `main` still needs `git pull`. `C:\otbase` is a throwaway worktree (`git worktree remove C:/otbase` when done).
  Possible follow-up: the editor box is a fixed 22em tall instead of filling the panel.
- **Phase 17 (NEXT_SESSION.md Part 2): DONE (2026-11-03, branch `claude/opus-phase-17-mcp-alerts-06250f`, built on top of the GUI-mode commit `d1041b4`).** Spec `docs/specs/PHASE_17.md`.
  MCP server (`openterm/mcp/`, `POST /mcp` + stdio bridge, `docs/MCP.md`), alert delivery (`openterm/delivery/`, email/Telegram/webhook, `DLVR` panel, migration 15), daily brief (`brief.py`,
  `BRIEF` panel, apscheduler job). SMTP TLS item closed. Gate ALL PASS (pytest 1694, e2e 223). Bench 34/37 and 32/37; the base commit without Phase 17 scored 32/37 under the same load
  (`docs/PERFORMANCE.md` "Phase 17 bench"), so the misses are machine load. Live smoke (fixture server): MCP stdio initialize + tools/list (17) + quote OK; brief built all 5 sections.
  **Not verified:** a real SMTP server, a real Telegram bot and a real webhook (no keys here; all send paths are unit-tested with fakes); Claude Desktop actually connecting to the MCP bridge.
  **Decision left to the user:** the DLVR `DESKTOP` toggle is stored, but desktop notifications already fire whenever the browser grants permission (`command/alerts.ts` `desktopNotify`, from ALRT);
  gating them on the toggle would silence existing users, so it was left as is.
  **Next:** user review, merge `d1041b4` + this branch into `main`, then Part 3 (better strategy editor) in a fresh session.
- **GUI mode, NEXT_SESSION.md Part 1: DONE, uncommitted (2026-11-02, branch `claude/opus-orchestrator-6b3fee`).** One app, two shells: `mode` setting (`settings/schema.ts`; new user = gui,
  saved object without `mode` = terminal; backend `settings_store.py` accepts `mode`), toggle in the status bar / `Alt+G` / `SETTINGS MODE`. GUI shell in `frontend/src/gui/` (menu bar, sidebar search,
  symbol picker, panel toolbar `toolbars.ts`, help drawer `Alt+H`, banner, welcome card, tour). `functions/categories.ts` maps every function to a menu category (a vitest fails on a missing one).
  `components/PanelNote.tsx` = shared loading/empty/error/stale look; 8 panels polished (CSS in `src/polish/lists.css`, `analysis.css`). e2e and bench seed Terminal mode (`openApp(page, {mode, welcome})`).
  Gate ALL PASS (pytest 1630, e2e 220). Bench 36/37: only the server-side BT 10-year run missed (717 then 500 ms vs 300; back-to-back runs after the gate), see `docs/PERFORMANCE.md` "GUI mode bench".
  **STOPPED on the bench stop rule:** the BT 10-year line failed 3 runs (717, 500, 698 ms vs 300). Backend code differs from `main` only by the settings `mode` field, so this is very
  likely machine load (about 23% idle CPU from Hermes, Google Drive, Brave, `serve.py` servers). Third run was 34/37 (also chart pan 33 ms, BT open-to-paint 104 ms; both passed earlier).
  **Resolved by a `main` baseline (2026-11-02):** `main` under the same load scored 34/37 and 32/37 with the same misses (BT 10-year 488-666 ms, BT open up to 123 ms), so the misses are
  machine load, not GUI mode (table in `docs/PERFORMANCE.md` "GUI mode bench"). Optional: one bench on a quiet machine for a clean 37/37 record.
  **Next:** user review + commit, then Part 2 (Phase 17) in a fresh session.
  Known gaps: FA statement table is a canvas grid, so it was not restyled (needs `Grid.tsx`); the tour text names `Alt+H` literally; the bench needs `OPENROUTER_API_KEY` unset in its shell (env key = 409 on the fake key).
- **Next session plan (2026-11-02):** `docs/specs/NEXT_SESSION.md` is the Opus-orchestrator super prompt: GUI mode + redesign, then Phase 17 (MCP, alert delivery, daily brief), then a better strategy editor. The editor itself already exists (`BtEditor.tsx`); the "not built" note at the step-4 line below is stale.
- **Public release (2026-11-02):** `ImTheRealARB/OpenTerm` is a public GitHub repo (history scanned, no secrets; a fresh clone installs in about 40 s and serves HTTP 200).
  README rewritten (beginner install steps, speed table from `docs/PERFORMANCE.md`, disclaimers) with new screenshots in `docs/screenshots/`. `scripts/setup(.ps1)` is now the LIGHT install
  (`uv sync --no-dev`, `npm ci`, about 330 MB); `-Dev` / `--dev` adds test tools and Chromium (about 1.5 GB more). The `start` scripts run `uv run --no-dev`.
  **Open (needs the user):** commit and push these doc changes; optional prebuilt-frontend GitHub Release (users then need no Node); optional lite/full split of scipy, statsmodels and arch (about 160 MB);
  macOS/Linux scripts and Docker are still untested.

## Earlier: end of the review sprint and terminal-look session (2026-10-19)
- **State:** everything is on `main` (local; the user decides when to push `origin/main`): Phases 1-16 and 19, the review sprint (`docs/review/SUMMARY.md`, `DECISIONS_FOR_USER.md`,
  `REVERTED.md`, `BASELINE.md`) and the terminal-look restyle (yellow command field with GO, key-hint row, ticker/name title bands, amber grid headers with rules, blue selection,
  `components/dataColors.css`). Final gate ALL PASS (pytest 1628, ruff, tsc, vitest, e2e 183) in 123 s; bench 37/37 (BT rows can miss when throttled: rest 2 min, rerun once).
  `UNLK` is NOT BUILT (DefiLlama emissions are paid). Phases 17-18 stay paused by the user.
- **Run it:** type `openterm` in any terminal (one-time `.\scripts\install-launcher.ps1` from the main checkout writes `openterm.cmd` into a PATH folder; `-Remove` undoes it).
  It runs `scripts/start.ps1`: builds the frontend if stale, serves http://localhost:8000, opens the browser. Flags: `-NoBrowser`, `-Rebuild`.
- **Dev loop:** `.\scripts\check.ps1` (affected tests + tsc + ruff), `node scripts/gates.mjs` (full gate, ruff/tsc first, heavy suites parallel, timing line), Playwright runs 4 workers
  (10 flaked 8-9 tests per run, on main too: rerun a failing spec alone before suspecting a change), `python scripts/new_function.py FOO` scaffolds a panel.
- **Next (optional, user decides):** read `DECISIONS_FOR_USER.md` (deferred risky items: cache table never pruned, SMTP TLS verification, Yahoo batch limit, execute.ts edit-before-validate,
  SWARM/AI stream abort on close vs remount, quant edge cases); retry the reverted ChartView buffer-transfer and SWARM abort with a browser open; unaudited modules (`valuation/`,
  `quantlib/`, most of `quant/`); still unverified: new 5-job CI on GitHub, `check.mjs` Playwright stage, heartbeat on a real half-open socket, Kite against a real key.

## Phase 11-12 notes (history, written when Phase 12 closed)
- **Steps 12.3 to 12.6 are done and committed.** Gates after step 6: 315 pytest + 9 xfail (8 for steps 7-8, 1 Phase 11
  recording), ruff, tsc, 192 vitest, 80 Playwright, bench **24/24** on the third run (two runs missed on machine noise;
  BT run 286 ms of 300, cached 5 ms, BT open 72 ms; see `docs/PERFORMANCE.md`; the BT run budget has little headroom). Step 4 also added VaR 95 / ES 95 (`bt/job.py` `tail_risk`, decision H was missed in step 3).
- **What step 5 added:** `bt/engines/` `india_equity.py`, `crypto.py`, `forex.py`, `futures_base.py`, `global_futures.py`,
  `composite.py`, `bands.py` (ported from Vibe `d0db2e3`, THIRD_PARTY.md rows added), wired in `bt/engine.py`; all six
  `ENGINES` tests pass against Vibe's own numbers. Ours: `composite.market_of` (Vibe's detector reads `BTCUSDT.P`, `BRK-B`,
  `^GSPC` as China A; unplaceable symbols raise), `providers/crypto.py` `BinanceKlinesProvider` (`binance_klines`, first in
  the `history` order in `main.py` and `config.yaml`; spot `BTCUSDT`/`BTC-USDT`, perp `BTCUSDT.P` with `Bars.fund` =
  mean funding per bar), `frames.from_bars` reads `fund`, `catalog.py` (`BUILT`, `SLIPPAGE_KEYS`, `COSTS`,
  `bars_per_year()`), API sets `interval` + `funding_rate` 0 for crypto/composite and refuses `SLIP` on forex. New tests:
  `tests/test_phase12_engines.py`. **Not ported:** Vibe's crypto `perpetual_strict` (needs mark prices and maintenance
  brackets; the engine refuses it), see `docs/DATA_LIMITS.md`.
- **The permission classifier denied running a copy script** over the downloaded Vibe sources, so the ported files were
  written by hand from reading them (headers name the source file and the changes). Vibe sources were fetched with
  `curl` from `raw.githubusercontent.com/HKUDS/Vibe-Trading/d0db2e3/...` into the scratchpad only, never into the repo.
- **What step 4 added:** `functions/BT.tsx` (views CHART / METRICS / TRADES / CODE cycled with `V`, not `Tab`; labels of
  decision L; progress from `J` frames; `R` re-run, `X` cancel, `E` CSV of the visible view), `bt/ruleParse.ts` (mirror
  of `bt/rules.py`), `bt/metricsFormat.ts`, `btApi` in `net/api.ts`, `adoptJob` in `net/jobs.ts`, ChartView `lowerPane`
  (drawdown) and lazy indicator worker, BT intent prefetch, `btOpen` perf series, bench section H + `btBench()`.
  `BT RUNS/EXPORT/MC/WF/SAVE/LOAD/DEL` say NOT BUILT YET with their step. **Not built yet: the Python strategy editor**
  (spec section 1: textarea + `BT SAVE/LOAD/DEL`); call it step 4B, before step 9.
- **What step 6 added:** `bt/validation.py` (Vibe's `monte_carlo_test`, `bootstrap_sharpe_ci`, `walk_forward_analysis`; matches
  Vibe's numbers), `bt/validate_job.py` + job kinds `bt.mc` / `bt.wf` (server-submitted, `POST /api/bt/runs/{id}/mc|wf`),
  frontend `BT MC|WF <run args>` and `M` / `W` keys, MC and WF views, `bt/validationFormat.ts`. Tests:
  `tests/test_phase12_validation.py`, vitest + 3 Playwright tests. **Not yet checked against the real backend in a browser:**
  do one smoke run (fixture mode) at step 9, with RUNS and IMPORT.
- **What step 7 added:** `bt/export.py` (CSV parts, Pine v5 translation of rule runs), `GET /api/bt/runs/{id}/export`, `GET /api/bt/compare`,
  frontend `functions/BtRuns.tsx` (`BT RUNS`: list, `C` marks two, comparison with metric diffs and the two equity lines),
  `BT OPEN`, `BT EXPORT`, `P` key, `csv.ts` `downloadText`. Tests: `tests/test_phase12_export.py`, vitest, 5 Playwright.
- **Bench note (closed):** the step-7 misses of the BT-run budget were machine throttling; the phase bench after a rest reads 233.6 ms (see below and `docs/PERFORMANCE.md`).
- **What step 8 added:** migration 10 `local_bars`, `bt/csvimport.py` + `bt/localdata.py`, `DataService.local` (set in the lifespan), `/api/bt/import`
  (POST/GET/DELETE), `bt/csvImport.ts`, `functions/IMPORT.tsx` (paste box with live preview, list, `D` twice). Tests: `tests/test_phase12_import.py`,
  vitest, 4 Playwright. Gates after step 8: 354 pytest + 1 xfail (the Phase 11 recording), 196 vitest, 87 Playwright, all green.
- **What step 4B and 9 added:** `functions/BtEditor.tsx` (`BT EDIT`/`LOAD`: list or editor), `BT SAVE name RULE`, `BT DEL name`, `@name` in the rule
  position (`bt/ruleParse.ts` `strategy`), docs (`COMMANDS.md`, `CHANGELOG.md`, `DATA_LIMITS.md`, `PERFORMANCE.md`), real-backend browser
  smoke run (all green; found the Ctrl+K-in-textarea bug). Final Phase 12 gates: 354 pytest + 1 xfail, 198 vitest, 92 Playwright, bench 24/24.
- **Scope and plan (decided by the user 2026-10-19; do not relitigate):**
  - **Full scope, Phases 12-19, minus paid-only data.** Removed: `TRAN`, `SEG` (paid FMP). Keys: keyless sources
    first; free sign-up keys are fine (Finnhub free tier for `EE`/`ANR` only as far as it covers them, Alpaca/Finnhub
    for real-time L1, EIA, Telegram bot token, the user's own SMTP); the **only paid service is OpenRouter**, default
    model a DeepSeek model chosen in `SETTINGS AI`, with the Phase 11 daily spend cap. Brokers: Alpaca paper first;
    Zerodha only if its API is free when the Phase 18 spec is written. A source that turns out paid-only is dropped
    and noted in DATA_LIMITS.md, never faked.
  - **Roadmap defaults are pre-approved** for every phase: write each spec with its defaults, then go straight on to
    tests and code. Stop only for a decision the roadmap did not foresee, a gate failure that needs a decision, or a
    missing key (OpenRouter before Phase 16: ask the user to set it with `APIKEYS`; then finish the `@RECORDING` test).
  - **Speed levers (approved):** (1) port Vibe modules in bulk by copy script with their tests converted to pytest
    and cross-checked against Vibe's values, independent modules on 2 Sonnet agents at most; (2) pre-approved
    defaults (above); (3) build shared templates first (keyed provider adapter, table panel, canvas heat grid) and
    keep later functions thin; (4) spec + tests in one step per phase, all of a phase's fixtures in one recording
    script run; (5) faster gates (test-suite audit running in its own session on its own branch, see below).
    Quality, accuracy, terminal speed and bench budgets are never traded for pace.
  - Estimate: about 9-13 hours of active work (4-5 sessions of one 5-hour window each). Re-check after Phase 12.
  - **Test audit: finished and MERGED (2026-10-19, `863af15`, no conflicts, all five gates green).** Branch
    `refs/heads/claude/test-speedup`, commit `5347a9b` (off `976c7ad`, 23 files). What it does: pytest 39-41 s -> 20-29 s
    (httpx client / CA bundle built once per worker in `conftest.py`; `addopts` `-n 6 --dist worksteal`), Playwright
    30-45 s -> 18-27 s (shared `openApp()` in `e2e/app.ts` loads the page once; web server builds without the type check),
    vitest 2.1 -> 1.3-1.6 s (`threads` pool). Merged duplicates: four migration-upgrade tests -> one test upgrading from
    every schema version 0-9 (`test_userdata.py`), three restart-survival tests -> one. Fixed flake:
    `test_runtime_limits_fail_closed` (3 s limit only on the time-limit case). Every old assertion kept.
    After merging: a new migration must list its tables in `TABLES_BY_VERSION` (`test_userdata.py`), or a check fails;
    `phase12.spec.ts` can switch its setup to `openApp()`. Left as is: ~700 unmocked Playwright requests
    (`/api/cmdhistory`, `/api/sources`, `/api/alerts`, `/api/settings`) reach port 8000, so keep port 8000 free during
    e2e; two Phase 6 insider tests wait ~1.7 s each on the real SEC rate limit (by design).
- **What step 3 added** (`backend/openterm/bt/`):
  - Ported verbatim from Vibe-Trading `d0db2e3` by a copy script (header line names the source): `models.py`,
    `metrics.py`, `rebalance_mask.py`, `engines/hooks.py` (= `_market_hooks.py`), `engines/global_equity.py`,
    `engines/base.py` (cut: loaders, optimizer, fundamentals/events, run card, artifacts; `run_backtest` replaced by an
    in-memory `run(data_map, signal_map, bars_per_year, bench_ret, benchmark_metadata)`; the rest unchanged).
  - Ours: `engine.py` (`backtest()`, `FEES=` overlay on `calc_commission`), `frames.py` (Yahoo chart / router `Bars` /
    Binance perp -> frames; `adjusted()`), `rules.py` (pure parser + `signals()` + `parse_command`), `sandbox.py`
    (AST allowlist + restricted builtins + guarded import + sockets off), `limits.py` (memory cap: Windows Job Object
    per worker, `RLIMIT_AS` elsewhere), `catalog.py` (engine per symbol, built engines, default costs), `job.py`
    (worker side of `bt.run`), `store.py` (data files, strategies, runs; keep 200).
  - Jobs: `Kind.internal` (bt.run only via `/api/bt/run`), `Kind.hash_view` (bt.run hashes without its labels),
    per-job `time_limit_s`, `JobRunner.on_done` hooks (store the run before the job shows done), `JobStore.forget(hash)`.
  - Migration 9 (`strategies`, `bt_runs`; a migration may now be a list of statements). API: `POST /api/bt/run`,
    `GET /api/bt/runs`, `GET|DELETE /api/bt/runs/{id}`, `GET /api/bt/strategies`, `GET|PUT|DELETE /api/bt/strategies/{name}`.
    Fixture routes for the 10y charts. Dependencies added: numpy, pandas (<3), psutil, keyring (decision M: APIKEYS now
    uses the Windows keyring).
- **Changed from the spec (tell the user):** default benchmark is Vibe's (equal-weight buy and hold of the traded
  symbols), not SPY; `BENCH=SPY` compares with an index. Needed so API runs match the Vibe cross-check exactly.
- **Still open from Phase 11:** the OpenRouter recording (`scripts/record_llm.py`, then delete `@RECORDING`).
- **The user's working rules for Phases 11-19** (updated 2026-10-19 to speed things up; quality and terminal speed
  must not drop):
  1. Do a whole phase per turn, step by step in HANDOFF order, committing each step. Stop only on a gate failure that
     needs a decision, a missing key, or a real product decision.
  2. Each phase starts with `docs/specs/PHASE_<n>.md` (defaults at the top, pre-approved: see "Scope and plan"),
     written together with its tests in one step, then code.
  3. One fresh session per phase (HANDOFF.md carries the state). Sonnet subagents only, at most 2 at once, only for
     truly parallel pieces (backend and frontend halves).
  4. Every step: `uv run pytest -q`, `uv run ruff check .`, `npx tsc --noEmit`, `npx vitest run`, `npx playwright test`.
     `node scripts/bench.mjs` at the end of each phase and on any step that touches rendering, hot paths or the bench;
     a phase is not done while any budget regresses. Record bench numbers in `docs/PERFORMANCE.md`.
  5. Docs (HANDOFF.md, CLAUDE.md): only the changed sections.
  6. At 95% of the 5-hour or weekly limit: stop subagents, write the state to HANDOFF.md, commit, and stop.
  7. Keep output small. If a key is needed, stop and say which one.
  8. **Sonnet for everything** (main session and subagents; decided 2026-10-19, no model switching). If the same gate
     fails twice on the same problem: stop, write the state and exact next action here, commit, and tell the user.
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

## Where things stand (as of Phase 10; Phases 11-19 are in "Resume here")
- **All 10 phases are built, verified and on `main`** (Phases 1-4 `736d6d5`..`b72466a`, 5 `4b3814c`, 6-10
  `96d40b9`..`f0df226`, then docs and the post-merge fixes). `main` was fast-forwarded on 2026-10-17; the old
  phase worktrees and branches were removed. Phases 11-16 and 19 were merged later (see "Resume here"); `origin` is the private GitHub repo ImTheRealARB/OpenTerm. The git identity (ankithrbharadwaj) is set for this repo only.
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
3. Phases 11-16 and 19: DONE and on `main` (plan in [docs/ROADMAP_PHASES_11-19.md](docs/ROADMAP_PHASES_11-19.md) and
   [docs/FEATURE_GAP.md](docs/FEATURE_GAP.md); Phases 17-18 paused by the user). The step table below is the Phase 11-12 build record.
   Steps (one commit each; a step is a spec, a tests set, or one function's code):

   | Step | State |
   |---|---|
   | 11.1 Spec [docs/specs/PHASE_11.md](docs/specs/PHASE_11.md) | **done**, defaults approved 2026-10-18 |
   | 11.2 Tests set: `backend/tests/test_phase11.py` (39), `frontend/src/net/phase11.test.ts` (5), `frontend/e2e/phase11.spec.ts` (4) | **done**; all marked expected-to-fail per step (see CLAUDE.md) |
   | 11.3 Key store, redaction, `/api/keys`, `KEY REQUIRED`, `APIKEYS` panel | **done** (backend by the main session, frontend by one Sonnet subagent) |
   | 11.4 Job runner, migration 8, `J` frames, `JOBS` panel, bench budgets (JOBS + APIKEYS open) | **done** (backend main session, frontend one Sonnet subagent); bench 21/21 |
   | 11.5 LLM gateway + health | **done except the recording** (main session, no subagents); bench 21/21 on the third run. `test_recorded_openrouter_stream...` waits for the OpenRouter key (`scripts/record_llm.py`) |
   | 11.6 `THIRD_PARTY.md`, CLAUDE.md rule changes, docs, phase verification | **done** 2026-10-19; bench 21/21 first run |
   | 12.1 Spec [docs/specs/PHASE_12.md](docs/specs/PHASE_12.md) | **approved** 2026-10-19 |
   | 12.2 Tests set + recordings + Vibe cross-check values | **done** 2026-10-19: `backend/tests/test_phase12.py` (75; markers `CORE` step 3, `ENGINES` 5, `VALID` 6, `RUNS` 7, `IMPORT` 8), `frontend/src/bt/phase12.test.ts` (6), `frontend/e2e/phase12.spec.ts` (5); fixtures by `scripts/record_phase12.py`; expected values `bt_vibe_expected.json` by `scripts/vibe_crosscheck.py` |
   | 12.3 Engine core, rules, sandbox, API, migration 9 | **done** 2026-10-19: all gates green, bench 21/21, THIRD_PARTY rows added |
   | 12.4 `BT` panel + BT bench budgets | **done** 2026-10-19: bench 24/24; strategy editor split out as 12.4B |

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
- CI (`.github/workflows/ci.yml`: static, then pytest / vitest / e2e jobs, then bench) is pushed to GitHub; bench timing on GitHub runners is untested, so a bench miss there may be the runner.
- Shell scripts `scripts/setup`, `scripts/dev` and `scripts/check.sh` are untested on macOS/Linux.
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
The pattern is in `frontend/e2e/*.spec.ts`. Current look: `docs/screenshots/` (five 2x shots of the live app, taken 2026-11-02).
