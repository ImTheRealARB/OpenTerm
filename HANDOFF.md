# Handoff

Last updated 2026-11-16 (UI parity pass merged, PR #50, merge commit `63c22f1`). Before that: 2026-11-15. Everything is merged to `main`; start new work
from `main`. The older copies of this file on `claude/gifted-galileo-w6y22a` and `claude/admiring-archimedes-7ibeha` are superseded.

## Resume here

**RESUME HERE: Phases 21-32 gap pass (2026-11-25).** Local `main` was fast-forwarded to the Phases 21-32 branch tip (`cf25759`,
owner's request, NOT pushed). Two Sonnet sessions audited all 100 picks against the code and built the missing ones on
`claude/gaps-21-27-chart-5df9b3` (4 commits) and `claude/gaps-28-32-data-82eb6f` (5 commits); both are merged into
`claude/handoff-phases-21-33-c6fd04` with this doc update. Audit files (local only): `docs/review/GAPS_21-27.md`, `GAPS_28-32.md` in those worktrees.
- Built: BT OPT custom `FIT=` formulas (`bt/fitexpr.py`, ast allowlist, no eval); REPLAY `STOP=` / `TARGET=` (`chart/replay.ts`
  `decideExit` = TS port of `bt/stops.py`); Kite DOM depth (`world/kiteflow.py`, `KiteTicker.pin(sym, depth=True)` = full mode for one
  instrument, 90 s); Kite tick-rule TAS (REST route pins the symbol, no `/ws` path; label ESTIMATED (TICK RULE)); Kite recording in `REC`
  (`kt` / `kd` lines; FOOT refuses a Kite session); EQS SEC formula fields (`/api/fund/eqsfund`, percent units); `IBQ 2024 SIC|DIV`; BIO DEF 14A name
  match (full-text search; the proxy board table is NOT parsed); new `ETS` (EU verified emissions by holder name, no ticker map); MA
  deal values (`filings/ma_value.py`, cover-page valuation or value-word sentence, never a per-share price).
- Skipped with reason: XBRL customer concentration (needs every filing's full XBRL instance, several MB each); NY Fed Staff Nowcast
  (the only workbook is a frozen archive ending 2021-08-27); Zillow (terms page answers 403, so terms unread; not bypassed).
  Dropped by the owner: IMF papers, NBER, revenue consensus. Phase 25 still deferred.
- **Next (new gaps the audit found, not built, usage ran short):** FX options should fetch the two rates (FRED / central bank)
  and the pair's past vol as labelled defaults (today `OV ... RF= RD=` must be typed); BIO should parse the proxy's board and officer
  table; RE needs India house prices (RBI HPI). CN news digest is a chip, not a card (by design, owner may want a card).
- **Owner checks on a day with a fresh Kite login:** `DOM RELIANCE.NS` and `DOM NIFTY26NOVFUT.NFO` (5 levels a side, compare with the
  Kite app; equity full-mode packets never recorded); `TAS RELIANCE.NS` while trading; `REC RELIANCE.NS ON` a few minutes, OFF, then
  `TAS|DOM RELIANCE.NS REC=<id>`, and the recording must stop with KITE LOGIN ENDED when the login expires. Checkable now:
  `GP AAPL REPLAY <date> STOP=5 TARGET=10`, `BT OPT ... FIT=SHARPE-2*DD`, `EQS ROE>15 MARGIN>10`, `IBQ 2024 SIC`, `AA ETS`, `AAPL MA`.
- Gate on the merged branch (2026-11-25, CI=1): ALL GATES PASS, pytest 4276, e2e 457 (smoke spec 88/88), vitest, tsc, eslint, ruff.
  The first two gate runs caught regressions the sessions' targeted tests missed (an MA fixture catch-all that hid older SEC fixtures,
  a 500 for Kite symbols on the crypto flow route, the BT OPT and MA smoke cases); all fixed. No bench this pass (no hot-path change).
  `test_phase24_recorder.py::test_the_disk_cap_stops_a_recording_and_says_so` failed once under 10 workers (KeyError 'BTCUSDT'), passes alone 3/3: watch it.

**RESUME HERE: Phases 21-32 build (started 2026-11-24, local commits, NOT pushed). Current branch
`claude/phases-21-32-build-resume-f09808` (worktree `.claude/worktrees/phases-21-32-build-resume-f09808`; fast-forwarded from
`...-8ff923` at 4565a3f). Phases 21-24 and 26-32 are DONE: Phase 25 deferred, so the 21-32 build is COMPLETE (Phase 29 gate 2026-11-24: pytest 4167, e2e 431; OIB needs a live Kite login to check). Phase 29 not built: EQS live-screener formula columns (only EQS BT has the fields), SIC grouping in IBQ, BIO boards from DEF 14A, EU ETS, MA deal values; CourtListener is doc-shaped (never run with a key). Phases 30-32: see their entries below. Branch pushed to origin 2026-11-24 with NO PR: the owner tests every feature by hand (local `docs/TEST_CHECKLIST.md` sections 28-38), then opens the PR to `main` himself (`main` has none of 21-32 yet). Phase 33 and Phase 25 are not started. To test: `cd .claude\worktrees\phases-21-32-build-resume-f09808; .\scripts\start.ps1` (or check out the branch in the main folder).**
- Worktree-only copies to bring back by hand (a hook blocks writes to the main checkout): `CLAUDE.md` and `docs/TEST_CHECKLIST.md` (both local only;
  checklist sections 31-35; newest copy in worktree `phases-21-32-build-resume-f09808`) goes over the main checkout's file.
- Owner's pick (2026-11-24, final): build ALL 100 items of Phases 21 to 32 except Phase 25 (deferred: nothing may depend on
  it) under the MINIMAL TEST BAR (local `docs/specs/PHASES_21-33.md` "How to run a phase" step 3) and the 95% 5-hour guard.
  The pick list is the whole of local `docs/specs/BUILD_PICKS_21-33.md`; no paste needed.
- Shared smoke spec: `frontend/e2e/smoke_new_functions.spec.ts` starts its OWN fixture backend on :8766 and forwards the
  page's `/api` calls to it (never :8000). Add one `CASES` line per new function / GP mode. `SMOKE_SHOTS=<dir>` saves a
  screenshot per case.
- **Phase 21 (chart depth I): DONE** (spec `docs/specs/PHASE_21.md`): 30 drawing tools + object tree + drawing schema 2,
  nine chart types (bricks, columns, high-low, step, volume candles), resampled candle lengths 2h..12mo + Binance 1s,
  PAT:GEO. Smoke 13/13. Gate and bench results: see the Phase 21 line in "Progress" below.
- Owner decisions to confirm later (defaults used, no blocking): HIGHLOW is drawn as high-low-close bars (the library
  always draws a close tick); COLUMNS start just under the lowest close, not at zero.

- **Phase 22 (linked panels and symbol math): DONE 2026-11-24** (spec `docs/specs/PHASE_22.md`), resumed in worktree
  `phases-21-32-build-resume-61e1cd` (branch `claude/phases-21-32-build-resume-61e1cd`, fast-forwarded from `...-2c2ded`).
  Where things live: symbol math `backend/openterm/symmath.py` (parser with the minus rule, printer, inner-join aligner),
  `service._history_formula` (each leg through `history`, envelope `formula` block), `/api/history/limits` per leg,
  stored synthetics `bt/localdata.py` `synth_*` + `/api/bt/synth`; command side `command/markets.ts` `isFormulaToken` /
  `isFormulaArg` (`AAPL/MSFT GP` and `GP AAPL/MSFT`), GP `FormulaNote` (no live ticks for a formula); IMPORT intraday
  `bt/csvimport.py` + `TZ=` + preview `looksIntraday`, IMPORT args `functions/importArgs.ts`; TRA / BETA panels
  (`TRA.tsx`, `BETA.tsx`, `BetaScatter.tsx`; BETA takes its symbol from args, `needsSecurity: false`); WL flags and sections
  `functions/wlFlags.ts` (keys F, Shift+F, H; `WL N FLAG|SECTION`), server `wlmeta.py`, mirror check in `test_ts_mirrors.py`.
  Gate (CI=1): pytest + vitest + lint ALL PASS, e2e 384 passed; the one failure (smoke BETA needed a panel security) was
  fixed and the smoke spec rerun 18/18. The final full rerun is folded into Phase 23's gate (the tree already held Phase 23
  work). No bench for Phase 22 (plan: bench after 21, 23, 27, 32). Deferred: none of the items; owner checks by hand.

- **Phase 23 (volume and order flow): BUILT 2026-11-24** (spec `docs/specs/PHASE_23.md`). GP studies `VP VP:S VP:A AVWAP AVWAP:W
  AVWAP:M AVWAP:A` (maths `chart/volumeProfile.ts`, `chart/avwap.ts`; painter `chart/profileOverlay.ts`, called from the GP overlay in
  `chart/gpLayer.ts`; anchors = the user's VLINE drawings; gauge `chart.profiles`), `TPO` (`functions/tpoMath.ts`, 5-minute bars),
  `DOM` / `LIQH` (`functions/domMath.ts`, reuse `/api/world/cdep`; LIQH memory only, 1,440 snapshots), crypto order flow
  `TAS BIGT FOOT` (Binance spot aggTrades: `world/orderflow.py`, `world/flow.py`, `/api/world/flow/{trades,bigtrades,footprint}`,
  capability `crypto_trades`, REAL fixture `binance_aggtrades_btcusdt.json`, recorder `scripts/record_phase23.py`).
  Deferred (owner to decide): India DOM from Kite depth and the Kite tick-rule TAS (`orderflow.tick_rule` exists + tested, not
  wired: needs a `/ws` subscription filtered on source `k`); volume profiles use the chart's own bars (labelled ESTIMATED FROM
  <interval> BARS), not finer bars fetched separately; the recorder stays off (owner decision 1 pending).

- **Phase 24 (replay and practice): BUILT 2026-11-24** (spec `docs/specs/PHASE_24.md`). `GP ... REPLAY [date]` (`chart/replay.ts`,
  `functions/useReplay.ts`; ChartView gets only the revealed bars; no-look-ahead test over every indicator), practice book (Shift+B/S/F,
  fills at the next bar's open, Shift+J saves to JRNL through the generic CSV import), linked replay (link-bus kind `replay`), recorder
  `REC SYM ON|OFF` (`recorder.py`, `recorder_routes.py` under `/api/recorder`, files in `<db dir>/recordings/`, SETTINGS RECORDER
  CAP|DAYS, off by default, loopback-only writes; `FOOT|TAS|DOM SYM REC=<id>` replay a session). Deviations: the practice book is
  per panel, not an ORD paper account, and has no stop / target orders (Phase 26 brings the intrabar rule); Kite tick recording not built.

- **Phase 26 (strategy lab): BUILT 2026-11-24** (spec `docs/specs/PHASE_26.md`). `BT OPT` = one `bt.opt` job running every
  parameter set through the normal engine (`bt/opt_job.py`; ~0.1 s per run on 10Y daily, serial): ranges `{lo..hi:step}` in a rule,
  or `NAME={..}` replacing a saved Python strategy's `NAME = 20` line (`bt/optspace.py`: parse, grid cap 2,000, seeded random and
  GA); guards, walk-forward and the efficient front from the returns matrix (`bt/overfit.py`: CSCV PBO 10 blocks / 252 splits,
  deflated Sharpe via `quantlib.multipletesting`, WF windows sliced from full-history runs, labelled). Exits `STOP= TARGET=
  FILL=INTRABAR` for BT and BT OPT (`bt/stops.py`, installed on the engine instance through `on_bar` / `_plan_open_order` /
  `_record_dropped_target_adjustments` hooks; ported engine files untouched; 60-minute bars for the last 2Y fetched by
  `api._intraday_for`). `BT LIVE` paper forward tests (`bt/fwd.py` book + `bt.fwdsig` job; routes `bt_lab_routes.py` under
  `/api/bt/opt` and `/api/bt/fwd`; state in kv `btfwd:<id>`; scheduler job `bt_fwd` every 15 min). Frontend: `functions/BtOpt.tsx`,
  `BtLive.tsx`, `bt/optArgs.ts`, `bt/liveArgs.ts`, `btOpt.css`. Deviations (owner to confirm): the forward test keeps its OWN
  paper book (fills at the next bar's open, raw prices, no fees) instead of ORD PAPER, because ORD needs Alpaca paper keys and a
  human confirm token per order and automating that would bypass the confirm step; fitness formulas over metrics were not built
  (fixed FIT= list); script strategies are out (Phase 25 deferred).

- **Phase 27 (scanners, indicator columns, smart alerts): MOSTLY BUILT 2026-11-24, paused at the 5-hour guard** (spec
  `docs/specs/PHASE_27.md`). One rule engine: `bt/rules.py` gained `ATR<n>` (Pine / MQL5 exports map it). `SCAN` = universe
  words (`scanner/universe.py`: SPX NDX DJI RUT MID via MEMB, `MEMB:` `WL:` `LIST:`, NIFTY50 / NIFTY500 from
  `providers/nseindices.py`) -> server bar download with progress (task in `app.state.scan_tasks`, polled at
  `/api/scan/task/{id}`) -> `scan.run` job (`scanner/job.py`); saved / scheduled scans in kv `scansaved:<NAME>` (cron
  `scan:<NAME>`, weekdays, sent through DELIVERY). Indicator columns `Q ... COLS=` / `WL NAME COLS=` (`scanner/cols.py`,
  `scan.cols` job, `/api/scan/cols`; frontend `functions/indCols.ts` + `useIndCols.ts`). Smart alerts `smart_alerts.py`:
  indicator alerts (`ALRT AAPL RSI14<30`, completed daily bars, `alerts.ind` job every 15 min, never fired in fixture mode) and
  drawing alerts (`ALRT AAPL LINE [N]`, checked per tick in `alerts_engine.py`); listed in ALRT as `S<id>`. `MRR` (index movers,
  contribution = weight x return, pure Python in `scanner/routes.py`). Frontend: `SCAN.tsx`, `MRR.tsx`, `useTaskPoll.ts`,
  `scanArgs.ts`, `net/scanApi.ts`, `net/smartAlertsApi.ts`. Tests: `test_phase27.py` (10), vitest `scanArgs` + `indCols`,
  smoke cases SCAN / MRR / ALRT / Q COLS= all pass. ETF screener `FSRC` (built by a helper agent): `providers/etf.py` +
  `etf_parse.py` (Nasdaq Trader symbol file, Yahoo fundProfile), `etf_screen.py` (paced background load, 3 profiles a second,
  progress saved, a restart resumes; a full live load is ~5,829 ETFs, ~37 min), `etf_routes.py`; frontend `FSRC.tsx`,
  `fsrcFilter.ts`, `fsrcData.ts`, `useFsrc.ts`, `net/etfApi.ts`, `net/etfTypes.ts`. `IMAP CRYPTO` / `IMAP ETF`: `IMAP.tsx` now has
  three data components on a shared `ImapBoard.tsx` (`imapUniverses.ts`, `useQuotePct.ts`); the US map is unchanged (phase19b
  IMAP e2e pass). Real trimmed fixtures `nasdaqtrader_etf_trimmed.json`, `yahoo_fundprofile_etf.json` (`scripts/record_fsrc.py`);
  tests `test_phase27_fsrc.py` (4) + vitest; smoke FSRC x2, IMAP CRYPTO, IMAP ETF pass.
  **Finished 2026-11-24 (commit "Phase 27 (finish)"):** `IMAP NIFTY` / `IMAP NIFTY500` (equal tiles grouped by industry: NSE's list
  has no weights; route `GET /api/scan/nifty`); FSRC toolbar (Details / Chart / Export); docs (COMMANDS, DATA_SOURCES, local
  TEST_CHECKLIST section 32). Bug found and fixed: `nseindices` was never in `ADAPTERS` / `DEFAULT_ORDER`, so every NIFTY universe
  (SCAN, MRR) was a 500; it is registered now with a doc-shaped fixture. Gate: pytest 4142 passed + 2 load flakes (both pass alone),
  vitest, lint all pass; e2e 395 passed, the smoke spec then rerun alone 42/42. Bench: 34/39, the same five misses as `main` benched in
  the same sitting (machine state, see `docs/PERFORMANCE.md` "Phase 27"). Not checked in a browser: the FSRC PARTIAL screen.

Progress (one line per phase; newest last):
- Phase 21: built 2026-11-24.
- Phase 22: built 2026-11-24 (gate green after one smoke fix).
- Phase 23: built 2026-11-24.
- Phase 24: built 2026-11-24 (committed together with 23; gate and bench in the commit message).
- Phase 26: built 2026-11-24 (gate result in the commit message; no bench this phase per the plan).
- Phase 27: DONE 2026-11-24 (finish pass in worktree `phases-21-32-build-resume-8ff923`; gate green apart from load flakes, bench = main).
- Phase 28: built 2026-11-24 (commit 99d8241). Phase 29: built 2026-11-24 (commit 4565a3f).
- Phase 30: built 2026-11-24 in worktree `phases-21-32-build-resume-f09808` (commit 6387245; gate: pytest 4181, e2e 449).
- Phase 31: built 2026-11-24 (committed with Phase 30 in 6387245 and finished with 32; gate fix: `GET /api/nb` is loopback-only now, the QRY field `margin` is `netmargin`).
- Phase 32: built 2026-11-24 (gate result in the commit message).

- **Phase 32 (AI inside functions): BUILT 2026-11-24.** Question chips: `functions/chips.ts` (pure, `chipsFor` / `chipLine`) + `?` in
  `ResearchPanel.tsx` (every table panel; while the list shows, 1-3 picks and Esc closes) -> `functions/askAi.ts` opens AI in a split with
  the question as args. Each question names the tool that reads the panel's data: new AI tool `board` (`ai/tools.py` `BOARD_FNS` = the 16
  Phase 30 boards + `res`), `qry`, `news`, `read_url`. CN digest = CN's first chip (headlines with time and source; lite: no dedicated card).
  ERN earnings card: `A` in ERN opens `AI FILING <SYM> EARNINGS` (preset `earnings` in `ai/filings.py`; `routes_filing.load_filing(earnings=True)`
  takes the newest Item 2.02 8-K, reads its EDGAR `<acc>-index.html` and picks the EX-99.1 row by TYPE (`filings.exhibit_991`; file names
  failed for NVDA and KO in a live probe), parses the release as one section). Checked live on NVDA, KO, AAPL releases (parse + retrieval,
  no model call). Revenue consensus is not shown (Nasdaq's calendar has EPS estimates only). Supply chain lite = the existing
  `AI FILING <SYM> CHAIN`; every FILING answer now says `AI-EXTRACTED`. NOT built: XBRL customer-concentration facts (SEC companyfacts drops
  dimensional facts, so the customer axis is not there). RES: `/api/macrod/res` (`macrod/service.res`, pure `res_filter`), provider
  `research_feeds` (`providers/macrod.py`, feed list `macrod/boards.RES_FEEDS`: BIS x2, Fed FEDS / Notes / IFDP, ECB papers + blog, RBI,
  arXiv q-fin), recorded by `scripts/record_phase30.py res` (fixtures `res_*.json`, manifest). `providers/news.py` now parses RSS 1.0
  (BIS). IMF papers: 403 bot check, not included; NBER dropped. Tests: `backend/tests/test_phase32.py` (6), `chips.test.ts`, aiArgs test,
  smoke case `RES SRC=BIS monetary`. No model call was made for any of this (AI answers need the owner's key).

- **Phase 31 (query language, Excel, notebooks): BUILT 2026-11-24.** `openterm/query/lang.py` (pure QRY parser, FLD catalog `FIELDS`,
  filter / sort / resample), `query/engine.py` (snapshot: universe -> screener fields -> quotes -> Yahoo key statistics, cheapest first,
  cap 150 symbols for the per-symbol stats; DATES mode: history and `FRED:<ID>` series, outer-joined by date), `query/notebook.py`
  (NB: `uv run --project backend --extra notebook jupyter lab`, 127.0.0.1, random token, notebooks in `<db dir>/notebooks`, repo
  `notebooks/*.ipynb` copied once, stopped in the lifespan teardown). Routes `query_routes.py`: `/api/query`, `/api/query/fields`,
  `/api/xl/{last,field,history.csv,query.csv}` (loopback only, GET), `/api/nb`, `POST /api/nb/{start,stop}` (loopback only).
  Backend `pyproject.toml` gained the `notebook` extra (jupyterlab + openterm-sdk from `../sdk/python` via `[tool.uv.sources]`;
  uv.lock grew by ~1,000 lines; a normal `uv sync` does not install it). SDK: `query()`, `fields()` (+2 tests). Excel: `docs/EXCEL.md`,
  `scripts/make_excel_workbook.py` -> `docs/excel/OpenTerm_examples.xlsx` (stdlib writer; never opened in real Excel here). Frontend
  `QRY.tsx`, `FLD.tsx` (ResearchPanel `loader`), `NB.tsx`, `qryArgs.ts`. Tests `test_phase31.py` (15) + vitest qryArgs + 4 smoke cases.
  Not verified: NB starting a real JupyterLab (needs the first `uv` install of jupyterlab) and the workbook in Excel: owner checks.

- **Phase 30 (macro, rates and commodities depth): BUILT 2026-11-24.** All 17 items. Backend package `openterm/macrod/`: `parse.py` (pure
  parsers: NY Fed, ECB ESTR, BoE SONIA, GDPNow and SPF workbooks, IMF DataMapper, OECD SDMX CSV, FOMC statement + word diff, TreasuryDirect,
  WASDE XML, EIA v2, NASS, Yahoo ETF valuation), `xlsx.py` (stdlib-only .xlsx reader; no openpyxl), `curves.py` (FWCV bootstrap, WIRP
  hike/hold/cut odds), `calendars.py` (CTM rules table, CDR hours mirror of `markets/hours.ts`), `boards.py` (every FRED id / ETF / country
  list), `service.py` (one async function per board). Providers `providers/macrod.py` (nyfed, ecb_estr, boe_sonia, atlfed, philfed, imf_dm,
  oecd_eo, fed_web, td_secs, wasde; eia and nass keyed + doc-shaped); `fx_panel` on Frankfurter, `etf_valuation` on yahoo_funds. Routes
  `macrod_routes.py` under `/api/macrod/<fn>`; WIRP odds are a new section of `/api/deriv/wirp`. Fixtures: `scripts/record_phase30.py`
  (REAL recordings, trimmed where noted; EIA / NASS doc-shaped) + `tests/fixtures/phase30_manifest.json` routed by
  `providers/macrod_fixtures.py` (first in ROUTE_TABLE). New key spec `nass` (NASS_API_KEY). Frontend: 16 ResearchPanel files
  (`api: "macro"`), `macroRowKey.ts` (row `go_fn` / `go_args` / `go_sym` jumps: CTM->CT, TSYS->YAS, WPE->DES). Tests `test_phase30.py` (14) +
  18 smoke cases. Deviations (owner to confirm): WCRS was an alias of FXC and is now its own function (alias removed); NY Fed Staff Nowcast
  not shipped (no clean download); Zillow not used (terms not checked); several OECD-on-FRED series stopped (India 10Y and policy rate,
  Japan policy rate and CPI, UK CPI): BTMM says so per row and uses the RATES curves / CENB policy source where the app has them; WPE ratios
  are Yahoo's holdings ratios, which Yahoo prints as reciprocals (inverted, test pins it); NRGF and AGRI crop condition never ran with a key.

**Update 2026-11-24: next-level planning (local-only docs, nothing built, nothing committed except this note):**
- A new feature gap and a phase plan exist **only on the owner's laptop**, never in git (they name other products):
  `docs/specs/FEATURE_GAP_PRO.md` (OpenTerm vs the professional terminals and charting platforms the owner named, feature by
  feature, with data source and confidence) and `docs/specs/PHASES_21-33.md` (12 phases after Phase 33 was dropped 2026-11-24 under the NO LIVE ORDERS rule: chart depth, linked panels, volume and
  order flow, replay, a scripting language, strategy optimisation, scanners and smart alerts, options analytics, SEC
  fundamentals depth, macro and rates depth, query / Excel / notebooks, and AI inside functions).
  Both are hidden by `.git/info/exclude`. **The owner picks feature by feature** (no bloat): the pick
  list is `docs/specs/BUILD_PICKS_21-33.html` (local only, 107 tick boxes, one per feature, built from the `.md` beside it).
  Ticks stay in the owner's browser; the owner presses "Copy my picks" and pastes the list into a session. Build only
  what was pasted: write its tracked `docs/specs/PHASE_NN.md` without product names, and build as in Phases 11 to 20.
- **NO LIVE ORDERS (owner decision 2026-11-24, in CLAUDE.md Non-negotiables):** Phase 33 is gone from the plan and the pick list. The live order code from Phase 18 step 1 was REMOVED on branch `claude/handoff-remaining-work-ac2782` (owner said so 2026-11-24): no `alpaca-live` or `kite` order broker, no `PUT /api/orders/live`, no `ALPACA_LIVE_*` key slot, the Kite client is GET-only, a live Alpaca host or a non-paper account is refused, `ORD ALPACA|KITE|LIVE` says `ORD PLACES PAPER ORDERS ONLY`. Kept: paper ORD, mandate, kill switch, ledger, read-only `SYNC`, JRNL. Every phase build checks the 5-hour limit and hands off at 95% (`PHASES_21-33.md` "How to run a phase" step 5).
- The test checklist (`docs/TEST_CHECKLIST.md` + its page `docs/TEST_CHECKLIST.html`, local only; rebuild the page with
  `python docs/build_checklist_page.py`) now has section 27 for the 2026-11-16 look-and-feel pass (216 items) and lists the
  Phase 21 to 33 plan under "Not built".
- State checked 2026-11-24: tag `v0.1.0` is on GitHub; the release is still a **DRAFT** with six installers (Windows `.msi` +
  `.exe`, two macOS `.dmg`, Linux `.deb` + `.AppImage`); PR #45 is merged; PR #49 (live AI run write-up) is open.

**Update 2026-11-16: UI parity pass (branch `claude/ui-parity-pass` from `origin/main` e135184, committed as `ec261e4` and pushed; MERGED to `main` 2026-11-16 as PR #50, merge commit `63c22f1`):**
nine look-and-feel changes taken from the reference terminal's conventions (no names, assets or wording copied):
1 GUI band colour `#7e001e`; 2 grouped command-line suggestions with More rows; 3 GUI "Related functions" button (the RELATED
window menu already existed); 4 yellow `?` help on every panel header; 5 row-number gutter + `rowNumbers` setting (the
digits-then-Enter jump already existed app-wide as number-select, so no second buffer was built); 6 board FLAG / change BAR /
`2DAY` sparkline (new `GET /api/sparks`, real fixture `yahoo_spark_2d.json`); 7 `Tile` component on HOME and DES; 8 GUI control
row under the band (dropdowns, ask field, Log checkbox); 9 light-grey GUI tab strip with function badge. Details: CLAUDE.md
"UI parity pass" (local-only file; summary of where each change lives: `command/groupSuggestions.ts`, `components/Panel.tsx`,
`components/Grid.tsx` + `microGraphics.ts` + `functions/boardGraphics.ts`, `GET /api/sparks`, `components/Tile.tsx`,
`gui/PanelToolbar.tsx` + `gui/toolbars.ts`, `gui/TabStrip.tsx` + `gui/tabLabel.ts`). Gate (CI=1, 2026-11-16): ALL PASS (pytest 4053, vitest, e2e 369/369). Bench 39/39 before and after
(`docs/PERFORMANCE.md` "UI parity pass"); startup bundle +1.6 KB gz (125.5 -> 127.1), accepted by the owner 2026-11-16.
Nothing in flight. Local gate rerun before merge: ALL PASS (pytest 4053, e2e 369/369).
Open design points: Grid decides the gutter by reading the registry and workspace itself (a `rowNumbers` prop from each panel
would be cleaner); in GUI the "Related functions" button and `RELATED ▾` sit side by side and do the same thing; the compact
`gp-range` dropdown now appears only in narrower panels (`wraps()` measures the band only); the Board legend does not mention
typing a row number. Why `2DAY` uses its own `/api/sparks` call: asking the quote call for `range=2d` would change
`chartPreviousClose`, which every change % is computed from.

Everything below is on `main` (merged through PR #40 after CI was green: static, pytest, sdk, vitest, e2e, bench). Work on the
session's designated branch and open a PR only when the owner asks.

**Update 2026-11-15 (branch `claude/openterm-v0-1-0-testing-f934c4`, commit `4c7a7a4`, pushed, NO PR yet):**
- Checked: tag `v0.1.0` is NOT on GitHub, no release exists, `release.yml` has never run.
- Pre-fixed a sure Windows failure: `tauri-build` stops with "`icons/icon.ico` not found" and the repo had only a 256 px
  `icon.png`. Generated the desktop icon set (`32x32`, `128x128`, `128x128@2x`, `icon.icns`, `icon.ico`) with
  `npx tauri icon` and listed them in `tauri.conf.json`. Not compiled here (no Rust on the owner's Windows machine).
  **This must reach `main` before the tag is pushed**, or the tagged commit lacks the fix.
- Live AI tests (step 6 below): waiting for the owner to enter `OPENCODE_API_KEY` in APIKEYS (Claude may not type a real key)
  and to approve spending Go quota on AI, AI AUTO, SWARM and AI BT CODE.
- Bench on GitHub CI: "BT 10-year daily rule run p95" read 300.0 / 298.2 / 233.5 ms (budget 300) on the last runs
  (`42905425073` main, `42918339742`, `42916274254`). p95 of n=12 is in effect the slowest run. Proposed, not done: split
  queue/dispatch vs engine time from the job timestamps, raise n, then decide between a speed fix and a CI-only budget.

**Update 2026-11-15, later (same branch; PR #43 with the icon fix MERGED to main as `8fa00df`):**
- Owner decision: **HANDOFF.md is public on `main`.** The owner removes `/HANDOFF.md` from `.git/info/exclude` and
  `HANDOFF.md` from `.worktreeinclude` in the main folder (a session cannot edit the base checkout); until then the
  pre-push hook blocks any push that touches HANDOFF.md.
- Bench headroom: the BT 10-year time is all inside the worker (POST ~5 ms, queue ~0 ms). Profiling showed `frame.loc[ts]`
  per bar = ~45% of the run; `_bar_row` now builds the same Series from a numpy copy (`b399dcf`, `test_bt_rowcache.py`,
  226 BT tests pass). Gain is modest (row lookup ~20% cheaper); A/B timing still to do on a quiet machine.
- DONE and merged into this branch (reviewed, gated): desktop sidecar (frozen backend via `desktop/sidecar/freeze.py`,
  Tauri shell plugin in `main.rs`, `externalBin` + resources, app-data DB, free-port fallback, `OPENTERM_CONFIG_PATH`,
  `OPENTERM_PARENT_PID`; notes `desktop/SIDECAR_NOTES.md`; new `.github/workflows/desktop-check.yml` + shared
  `.github/actions/build-sidecar`); settings per-field merge (`field_times`, server merge under a lock, `test_settings_merge.py`);
  English references for elliott-wave, harmonic, ichimoku and smc (no other skill has untranslated references);
  Windows skip of two POSIX file-mode asserts (`test_remote.py`, `test_mcp_client.py`).
- Gates on this branch (2026-11-15, Windows): ruff, tsc, eslint, vitest clean; pytest 4036 passed (after the file-mode fix);
  Playwright 342/354 with a fixture backend on :8100, the 12 failures all pass with NO backend (the documented setup;
  a live backend keeps settings between tests). Full bench NOT rerun (owner's app holds :8000); BT A/B in PERFORMANCE.md.
- NOT verified: the Rust shell has never compiled (no Rust here). `desktop-check.yml` is its first compile and runs on a PR
  touching `desktop/`. `Cargo.lock` was not regenerated: commit the lock the first build produces. macOS/Linux frozen
  builds untried. One-file start takes 8-20 s with no splash.
- **PR #44 OPEN** (https://github.com/ImTheRealARB/OpenTerm/pull/44, branch `claude/openterm-v0-1-0-testing-f934c4`).
  At hand-over CI was running: static and sdk passed; pytest, vitest, e2e and `desktop-check` (shell on windows / macos /
  ubuntu) pending. Auto-fix was on in the old session only; a new session must check CI itself (`gh pr checks 44`).
- **Next, in order:**
  1. Get PR #44 green. Most likely failure: `desktop-check` (first Rust compile ever). Read the job log
     (`gh run view <id> --log-failed`), fix `desktop/src-tauri/src/main.rs` / `Cargo.toml`. A local session on the
     owner's laptop pushes to the same branch. **A cloud session can push only to its own designated branch:** start
     it from this branch (`git fetch origin claude/openterm-v0-1-0-testing-f934c4` and `git merge --ff-only FETCH_HEAD`
     into the session branch), push fixes there, and when the owner asks, open a PR from it that replaces #44 (then close
     #44 with a comment pointing to the new PR). If the box has cargo, `cargo check` in `desktop/src-tauri` catches Rust
     errors before CI (Linux needs the webkit packages listed in `release.yml`).
     After the first green compile, commit the `Cargo.lock` the build produced (regenerate with `cargo generate-lockfile`
     on a machine with Rust) if it changed.
  2. Owner says merge: `gh pr merge <N> --merge` (local gate green is the bar; CI is extra).
  3. Owner tags `v0.1.0` on the Windows laptop (commands under step 2 below) and checks the "release" workflow.
  4. Owner-only, later: OpenCode Go live AI tests (owner types `OPENCODE_API_KEY` in APIKEYS, approves quota use, then
     run AI, AI AUTO, SWARM, AI BT CODE once each), macOS run on the MacBook Air, updater signing key, Kite / Alpaca /
     IBKR live tests once those accounts exist.
  5. Optional: more BT 10-year headroom on CI (now ~10% faster; the rest is the ported engine's per-bar Python loop;
     options in `docs/PERFORMANCE.md`), a splash window for the 8-20 s desktop start-up.
- **Cloud session 2026-11-15 (branch `claude/openterm-v0-1-0-testing-i4jf7x`, fast-forwarded from #44's branch):**
  step 1 result: PR #44 at `45ec69a` was ALL GREEN (15 checks: static, pytest, sdk, vitest, e2e, bench on both push and
  PR runs; `desktop-check` shell on windows-latest, macos-latest, ubuntu-22.04 = first Rust compile passed, no code fix
  needed). Only follow-up: `Cargo.lock` lacked `tauri-plugin-shell`; added with `cargo metadata` (minimal resolve:
  additions only, `tauri-plugin-shell 2.6.0` + its deps, no existing pin changed). Local `cargo check` not possible here
  (no webkit2gtk dev packages); the new PR's `desktop-check` compiles with the committed lock.
  Step 2 (owner approved): **PR #45 OPEN** (https://github.com/ImTheRealARB/OpenTerm/pull/45, replaces #44, which is
  closed with a pointer). #45 CI ALL GREEN at `c65f14a` (15 checks incl. `desktop-check` on 3 OSes with the new
  `Cargo.lock`), mergeable, no reviews. NOT merged: next is step 2 (owner says merge: `gh pr merge 45 --merge`).
- Owner's local folder (`C:\Users\Asus\Documents\OpenTerm`): `/HANDOFF.md` is out of `.git/info/exclude` (done
  2026-11-15). Still to do there: drop `HANDOFF.md` from `.worktreeinclude`, copy this worktree's `CLAUDE.md` over the
  main one, then `git pull origin main` after merges (back up / remove the old untracked HANDOFF.md first if git complains).

**Status (2026-11-10, end of session): ALL 13 WORKSTREAMS MERGED TO `main`. Next: the owner pushes tag `v0.1.0` (step 2 below).**
- Gates on the tip: ruff clean, pytest 4005 passed, typecheck + lint clean, vitest 1479 passed, Playwright 354/354, bench 39/39
  (tick to pixel p95 42.2 ms). Docs done: CHANGELOG, ROADMAP, FEATURE_GAP, PERFORMANCE, README badge, RELEASE_NOTES, DESKTOP.
- Local runs in this container need the preinstalled Chromium (`/opt/pw-browsers/chromium`): pass it as `executablePath` in a
  throwaway Playwright config / bench copy. Run e2e with NO backend on :8000 (stale settings there break GUI-mode tests).
  Never `scripts/start` / `npm ci` in a worktree whose `frontend/node_modules` is a symlink: it empties the shared copy.
- Decided 2026-11-10: ORD and JRNL keep their in-panel text boxes (written into DESIGN.md as the only two exceptions).
  NSE MCP presets live-checked with the owner's approval (results in docs/MCP.md): 9 of 10 allowed tools answered, 1 got
  NSE's 403 from the cloud machine.
- **What is left (owner decisions of 2026-11-10, end of session):**
  1. ~~Merge to main~~: done (PR #40).
  2. **First release `v0.1.0`: NOT DONE YET, the owner runs it on their Windows laptop** (the one with the OpenTerm folder).
     A Claude cloud session cannot do this step: its git proxy only accepts pushes to the session's own branch (a tag push
     gets HTTP 403), and its GitHub tools cannot create tags or releases. In PowerShell or Git Bash, inside the OpenTerm folder:
     ```
     git checkout main
     git pull origin main
     git tag -a v0.1.0 -m "OpenTerm v0.1.0"
     git push origin v0.1.0
     ```
     `git pull` first so the tag lands on the merged `main` (commit `6db6c98` or later); `git log --oneline -1` should show
     "Merge pull request #41" or newer. No folder handy? On github.com: Releases -> Draft a new release -> "Choose a tag":
     type `v0.1.0`, "Create new tag on publish", target `main`, then **Publish release** (a draft does not create the tag).
     Either way GitHub Actions runs `release.yml` (Actions tab, workflow "release"): Linux, Windows and macOS builds into a
     DRAFT release (Option A) or into the published one (Option B). The app version is already 0.1.0 in
     `desktop/package.json` and `tauri.conf.json`; `release.yml` refuses a tag that does not match. This workflow has never
     run: check its logs, and if a build fails, paste the error into the next session to fix.
  3. **Updater signing key: later.** `npx tauri signer generate`, then the secrets `TAURI_SIGNING_PRIVATE_KEY` (+ password) in
     GitHub Settings -> Secrets and variables -> Actions. Without it releases build fine but do not self-update.
  4. **NO Apple / Windows signing certificates (owner decision).** OpenTerm is an open-source GitHub project, not an app-store
     app; unsigned installers are fine. Do not add certificate steps or ask again.
  5. **macOS run: later, on the owner's MacBook Air.** `scripts/setup` then `scripts/start` (and optionally the desktop build in
     `docs/DESKTOP.md`); report anything that breaks.
  6. **Paid / keyed live runs: later.** The owner has an OpenCode Go subscription: set `OPENCODE_API_KEY` in `APIKEYS`, then
     `SETTINGS AI PROVIDER OPENCODEGO`, and run AI, AI AUTO, SWARM and AI BT CODE once each against it (record with the
     recorder scripts, label recordings). Kite, Alpaca and IBKR live checks need those broker accounts; until then they stay on
     doc-shaped fixtures.
  7. **HTML feature/command checklist:** lives only on the owner's other laptop; the owner updates it from this branch's
     CHANGELOG entry of 2026-11-10 and `docs/COMMANDS.md`.
- Optional: settings sync per-field merge; Chinese `references/` of elliott-wave, harmonic, ichimoku; bundle the backend as a
  Tauri sidecar.

Setup: `cd backend && uv sync --extra ocr`, `cd frontend && npm ci`. Fixture UI check: `OPENTERM_FIXTURES=1 uv run uvicorn
openterm.main:app --port 8000` + `npx vite preview --port 4180` (proxies `/api`).

Owner's rules for this work (2026-11-10):
- **At most 3 subagents at a time** (Sonnet is fine). Be careful with usage: small batches; stop when the owner says usage is high.
  On reaching ~95% of the 5-hour limit: pause, update this file, give the owner a handoff prompt.
- Do not run third-party MCP server packages (`npx stock-nse-india`, `uvx nse-mcp`) without asking the owner first.
- Commit and push only to the session's designated branch; no PR unless asked.

## What the owner asked for (2026-11-10)

"Finish all the paused or unplanned work", build the things left out on purpose where possible, "all the other stuff" (unverified
builds, doc fixes), and check whether an NSE India MCP server can be added. Answers given:

- **NSE MCP:** yes, through an MCP *client* in OpenTerm (workstream 03). Two candidate servers, both shipped as disabled presets:
  `stock-nse-india` (MIT, github.com/hi-imcodeman/stock-nse-india, `npx -y stock-nse-india mcp`, stdio, ~30 tools) and `nse-mcp`
  (github.com/jugaad-py/nse-mcp on jugaad-data, `uvx nse-mcp`, stdio, ~24 tools). Both unofficial, not affiliated with NSE.
- **Left out on purpose:** web search / URL reading can be built safely and opt-in (09); OCR as an optional extra (08). Still not
  buildable: China A-share skills (no data), transcripts and segments (paid only), `UNLK` unless a free source with fair terms exists (12).
- **Needs the owner, not code:** real Kite and OpenRouter recordings (keys), signed installers (Windows / Apple certificates),
  a macOS run of the scripts.

## Workstreams

Thirteen subagents started on 2026-11-10 and were stopped part-way (owner's request). Each one's work up to that point (committed and
uncommitted, against `b8a274a`) is saved as `handoff/patches/NN-*.patch`. Every patch applies cleanly to `main` on its own. Status is
the last thing each agent reported plus its file list: **verify by running its tests before trusting it.**

| # | Patch | Scope | State when stopped |
|---|---|---|---|
| 01 | `01-phase18-orders` | Phase 18 orders: `backend/openterm/orders/` (mandate, one-time confirm token, kill switch, hash-chained ledger, paper/live decided structurally), Alpaca paper + live, Kite live orders, `ORD` ticket + blotter, fills into PORT; AI never places orders | Backend core, broker adapters, doc-shaped fixtures written; was writing `test_phase18_orders.py`. **Not started:** frontend `ORD`, fills to PORT UI, `docs/specs/PHASE_18.md`, COMMANDS |
| 02 | `02-broker-sync` | Read-only Kite holdings + IBKR Client Portal Gateway (loopback only) sync into PORT; `SYNC` panel. No Alpaca (01 owns it) | Nearly done: backend, frontend, tests written; was about to run ruff and the full suite and commit |
| 03 | `03-mcp-client-nse` | MCP client (stdio + Streamable HTTP), `<data dir>/mcp_servers.yaml`, all servers off until enabled, per-tool allow-list, tools as `<server>.<tool>` in AI/SWARM, results wrapped as untrusted, ledger, order-name refusal, NSE presets | Backend client, routes, AI wiring, fake server and tests written. **Not started:** MCP panel/commands in the frontend, presets text + notice, `docs/MCP.md` client section, THIRD_PARTY entries |
| 04 | `04-jrnl` | `JRNL`: Zerodha / IBKR Flex / Alpaca / generic CSV parsers, FIFO round trips, stats, behaviour diagnostics, shadow account through BT jobs, read-only `journal` AI tool | Backend package and routes written. **Not started:** tests, frontend `JRNL`, docs |
| 05 | `05-sdk-source-pin` | `sdk/python` (`openterm-sdk`, DataFrames with source/as_of in `attrs`) and per-command source pin `SRC=` (no silent fallback when pinned; cache keys include the pin; `SETTINGS SOURCE ...`) | Backend pin + frontend `SRC=` parsing done; was writing vitest. **SDK barely started** (pyproject, errors.py); CI step not added |
| 06 | `06-extensions-hosting` | Extensions (entry points or `<data dir>/extensions/`, off until enabled, providers / read-only AI tools `ext.<name>.` / `/api/ext/<name>/` routes, generic `EXT` panel, example in `examples/extensions/hello/`) and self-hosted remote mode (`OPENTERM_REMOTE=1`, token login, cookies, MCP stays loopback, Caddy compose) | Extensions backend, `EXT` panel, example and tests written. **Remote/hosted mode not started**, no `docs/EXTENSIONS.md` / `docs/HOSTING.md` |
| 07 | `07-keyed-providers` | Twelve Data, Alpha Vantage, Polygon, FMP adapters (KeyedProvider), KEY_SPECS, hierarchy ranks, fixtures, `scripts/record_providers.py` | Adapters (`twelvedata.py`, `keyed_market.py`), fixtures (real ones only from the public `demo` keys) and recorder written. **Not wired** into `ADAPTERS` / `KEY_SPECS` / `hierarchy.py`; no tests; docs rows not updated |
| 08 | `08-ai-extras` | `ai.store_text` (side table, purge keeps the chain valid), optional OCR for AI DOC (tesseract if on PATH), `patterns` AI tool, AI BT SignalEngine code drafts, `AI FILING <SYM> GUIDANCE` / `CHAIN` | store_text, OCR and patterns with tests done. **Not started:** AI BT code drafts, GUIDANCE / CHAIN |
| 09 | `09-web-tools` | Opt-in `read_url` (SSRF guard: resolve and pin public IPs, re-check redirects, caps) and `web_search` (Brave / Tavily keys, optional SearXNG), untrusted wrapping, per-run caps, `SETTINGS AI WEB` default OFF, SWARM coverage computed | Netguard, fetcher, search, keys, settings, frontend settings written. **Not started:** tests (every SSRF refusal), SWARM coverage, `docs/AI_WEB.md` |
| 10 | `10-alpha-zoo` | Port the rest of Vibe-Trading's 478 alphas (data-driven), no-lookahead property test, `docs/ALPHA_SKIPPED.md`, crosscheck script | Large: ~436 factor files, port script, crosscheck, tests, skipped list. **Unverified:** tests not confirmed green, ALPHA job timing before/after not measured, THIRD_PARTY / spec counts not updated |
| 11 | `11-skills` | Port skipped Vibe skills: translate the non-China Chinese ones, map ones whose tools now exist (read_url, web_search, patterns, journal) | Only 6 English translations in `scripts/vibe_skill_overrides/`. **Not started:** port-script changes, regeneration, `docs/PHASE_20_SKIPPED.md` |
| 12 | `12-bt-exports-unlk` | `BT EXPORT` MT5 (MQL5), PDF report, XLSX; `UNLK` research | MQL5, PDF and XLSX exports, frontend and tests written; UNLK researched and written into `docs/DATA_LIMITS.md` (check its verdict). Needs ruff / full-suite run |
| 13 | `13-packaging` | Real Docker build + compose run, Tauri Linux build, Tauri updater + `release.yml`, run the Linux scripts | One Dockerfile change only; the build hit a **Docker Hub pull rate limit**. Tauri not started |

Merge notes: patches 01, 04 and 08 each append a migration to `MIGRATIONS` in `backend/openterm/db.py`; when applying more than one,
keep all of them, one after another. `main.py`, `ai/tools.py`, `registry.ts`, `categories.ts`, `toolbars.ts`, `keys.py`,
`settings_store.py` are touched by several patches; all edits were meant to be append-only, so keep both sides. Run
`python scripts/gen_functions_doc.py` after applying anything that touches the function registry (it regenerates `docs/FUNCTIONS.md`).

## After the workstreams

- Full gates: `uv run ruff check .`, `uv run pytest -q`, `npm run typecheck`, `npm run lint`, `npm test`, `npx playwright test`, then the
  bench (`scripts/bench`), including the tick-to-pixel rerun (last 55-59 ms vs a 50 ms budget).
- Docs: CHANGELOG entry; `docs/ROADMAP_PHASES_11-19.md` (Phases 17/18 status, Phase 19 says "not merged to main", stale);
  `docs/FEATURE_GAP.md` statuses; README benchmark badge says 37/37 while `docs/PERFORMANCE.md` has 39 budgets.
- Optional: settings sync is last-write-wins by `updated_at` (per-field merge would be better).

## Agent brief template (what each subagent was told)

Rules every brief included: read `DESIGN.md` and `docs/ADDING_A_FUNCTION.md` (and `docs/ADDING_A_PROVIDER.md` for data sources); never
fake data (`STALE` / `ERR` with source and age; test data labelled; doc-shaped fixtures say NOT A RECORDING; tests never hit the
network); zero keys still works (`KEY REQUIRED` via `KEY_SPECS`); secrets never reach the frontend, logs, URLs or error text
(`redact.redact()`); keyboard-first; new functions go in `registry.ts`, `categories.ts`, `gui/toolbars.ts`, lazy-loaded; no Python
per-bar loops in hot paths; heavy work in jobs. Run only targeted tests while others share the machine (`uv run pytest -n 2
tests/test_x.py`, `npx vitest run <path>`), then ruff, typecheck, lint and the full backend suite once. Append-only edits in shared
files. Agents do not edit CHANGELOG, README, RELEASE_NOTES, ROADMAP or FEATURE_GAP (the lead does). Commit messages end with the
session's attribution lines; no push from agents. Final report: commit, changelog bullets, tests and results, what is left and why.
