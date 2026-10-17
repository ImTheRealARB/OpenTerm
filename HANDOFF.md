# Handoff

_Last updated: 2026-10-17, session 4 (Phase 5 committed `4b3814c`; Phases 6-10 built in parallel worktrees, being merged here one phase per commit; Phase 6 merged, awaiting commit)._

> **Resuming in a new session or account?** Paste the prompt from [RESUME_PROMPT.md](RESUME_PROMPT.md)
> and read "Parallel build of Phases 6-10" below.

## Parallel build of Phases 6-10 (MERGING)
Status: **all five phases were finished in their worktrees (each green in isolation). The lead is merging them here in order
6, 7, 8, 9, 10, one commit each; the user approves every commit. Phase 6 is merged and verified, awaiting commit.**
The last column tracks the merge into this worktree.

| Phase | Worktree (under `.claude/worktrees/`) | Branch | Notes file | Merge |
|---|---|---|---|---|
| 6 FA, FIL/SEC, OWN, HDS | `openterm-p6` | `claude/openterm-p6-wip` | `PHASE_6_NOTES.md` | **MERGED + verified here** (see Phase 6 details); commit pending user approval |
| 7 FRED, MACRO, RATES, ERN, ECO | `openterm-p7` | `claude/openterm-p7-wip` | `PHASE_7_NOTES.md` | Finished in worktree, not merged yet (next) |
| 8 PORT, ALRT (migrations 6-7) | `openterm-p8` | `claude/openterm-p8-wip` | `PHASE_8_NOTES.md` | Finished in worktree, not merged yet |
| 9 EQS, HIST, CORR, COMP, CSV export | `openterm-p9` | `claude/openterm-p9-wip` | `PHASE_9_NOTES.md` | Finished in worktree, not merged yet; CSV-export hook wired into 6-8 panels after merge |
| 10 SETTINGS, themes, vim, keybinding overrides, Docker, Tauri, release notes | `openterm-p10` | `claude/openterm-p10-wip` | `PHASE_10_NOTES.md` | Finished in worktree, not merged yet |

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
  `claude/openterm-phases-5-10-a49ca4` (contains Phases 1-4). **Phase 6 is merged into the working tree and verified, not yet committed.**
- Phases 3 and 4 live on branch `claude/openterm-phase-3-4-621f59` (worktree), **not on `main` yet**.
  The main checkout has the Phase 3 files uncommitted on `main` (identical to `b6dca4e`). To bring
  `main` up to date: discard those local copies on `main` (`git checkout -- .` and delete the untracked
  Phase 3 files), then `git merge claude/openterm-phase-3-4-621f59` (fast-forward). No git remote. The git identity (ankithrbharadwaj) is set for this repo only.
- Latest verification (Phase 6 tree):
  - Backend: 90 pytest passed (`-n auto`, ~16 s), ruff clean.
  - Frontend: 46 vitest passed, tsc clean, 29 Playwright passed (`--workers=8`, ~19 s).
  - Bench: 17/17 budgets PASS, none regressed (see `docs/PERFORMANCE.md` Phase 6; one lone chart-pan miss on the first run was noise).

## Done
| Phase | Contents |
|---|---|
| 1 Scaffold | Shell UI (top bar, command line, clock + market lights, status bar), tiling workspace (split/close/focus/resize/maximize, panel history), command parser `[N:] SEC [MKT] FN [ARGS]`, fuzzy autocomplete, history, `keybindings.json`, PERF HUD/panel, `scripts/bench.mjs`, CI workflow |
| 2 Data core | Provider adapters (Yahoo, Nasdaq), router with fallback + circuit breaker, token buckets, LRU + SQLite WAL cache, SWR envelopes `{data, source, as_of, age_s, stale, fallback_from}`, request coalescing, `/api/quote|history|search|sources|log`, fixture mode, `SOURCES` and `LOG` screens, live ticker search with prefetch |
| 3 First functions | Yahoo protobuf streamer (hand-decoded), REST poll fallback, SYNTHETIC load stream, hub with one upstream subscription per symbol and per-client coalescing; `/api/profile`; frontend tick store (per-frame batching), canvas virtualized `Grid`, `Q` (live monitor), `DES`, `QR`, `GP` (lightweight-charts, indicators in a Web Worker, compare, log, crosshair, keyboard pan/zoom), `PERF GRID/CHART` load views |
| 4 Workspace | SQLite migrations 3-4 (`layouts`, `history`), `backend/openterm/userdata.py`, `/api/layouts[/{name}]` GET/PUT/DELETE, `/api/cmdhistory` GET/POST; `LAYOUT`/`MONITOR` `SAVE|LOAD|DEL name` (bare name = LOAD, bare `LAYOUT` = list panel with J/K, Enter, Del-twice, S), `Ctrl+S` (re-save current named layout, else prompts) / `Ctrl+O` (prompts `LAYOUT LOAD ` with name autocomplete), layout name in the status bar; command history moved to SQLite (batched writes, `sendBeacon` on exit, one-time upload of the old localStorage history); Playwright tests for layouts, history and Ctrl+Shift+Arrows resizing; bench gate for layout load |
| 5 Boards + lists | Watchlists (SQLite, `WL` grammar), news (`N`: RSS / Yahoo RSS / GDELT), `MOV` (Nasdaq movers), `CRYP` (CoinGecko, Binance), boards `WEI` `FX` `CMDTY`, `FXC` cross matrix, shared `quoteRows.ts`; pytest-xdist, fully parallel Playwright |
| 6 SEC + ownership | `FA` (SEC EDGAR XBRL financials: IS/BS/CF, annual/quarterly), `FIL`/`SEC` (filings list), `OWN` (Form 4 insider transactions), `HDS` (institutional + fund holders); providers `sec`, `yahoo_own`; needs `SEC_USER_AGENT` in env |

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

**Bench baseline for Phase 7** (Phase 6 tree, 2026-10-17): 17/17 PASS. Bundle 85.0 KB gz; backend p95
health/quote/history 0.7/0.7/1.9 ms; cold start 92.3 ms; keystroke 14.4 ms (9.8 under load); cached / cold-network
command to paint 18.5 / 18.1 ms; tick-to-pixel 38.2 ms; frame p95 16.7 ms everywhere; long tasks 0; heap 5.1 MB;
ticks 4,000/s; layout load 36.3 ms. (Phase 5 baseline: 84.8 KB, 37.5 ms tick-to-pixel, 35.8 ms layout.)

## Next
Phases 6-10 in order:
- 6: done (merged, see Phase 6 details).
- 7: MACRO/FRED (key), ECO calendar, RATES curve, ERN.
- 8: PORT (CSV import/export), ALRT with desktop notifications.
- 9: EQS screener, CORR, COMP, HIST, CSV export everywhere.
- 10: Themes UI, vim mode, keybinding overrides, SETTINGS, Docker, Tauri, release notes, full perf pass.

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
