# Handoff

_Last updated: 2026-10-17, session 2._

## Where things stand
- **Phases 1-4 of 10 are built and verified.** Phases 1-3 are committed (`736d6d5`, `3815fdd`, `b6dca4e`).
  **Phase 4 is NOT committed** yet: commit when the user approves.
- Session 2 worked in the git worktree branch `claude/openterm-phase-3-4-621f59` (Phase 3 + 4 live there,
  not on `main` yet). The main checkout still had the Phase 3 files uncommitted on `main`; they are
  identical to commit `b6dca4e`. No git remote. The git identity (ankithrbharadwaj) is set for this repo only.
- Latest verification (Phase 4 tree):
  - Backend: 42 pytest passed, ruff clean.
  - Frontend: 24 vitest passed, tsc clean, 15 Playwright passed.
  - Bench: 17/17 budgets PASS (new: layout load to paint).

## Done
| Phase | Contents |
|---|---|
| 1 Scaffold | Shell UI (top bar, command line, clock + market lights, status bar), tiling workspace (split/close/focus/resize/maximize, panel history), command parser `[N:] SEC [MKT] FN [ARGS]`, fuzzy autocomplete, history, `keybindings.json`, PERF HUD/panel, `scripts/bench.mjs`, CI workflow |
| 2 Data core | Provider adapters (Yahoo, Nasdaq), router with fallback + circuit breaker, token buckets, LRU + SQLite WAL cache, SWR envelopes `{data, source, as_of, age_s, stale, fallback_from}`, request coalescing, `/api/quote|history|search|sources|log`, fixture mode, `SOURCES` and `LOG` screens, live ticker search with prefetch |
| 3 First functions | Yahoo protobuf streamer (hand-decoded), REST poll fallback, SYNTHETIC load stream, hub with one upstream subscription per symbol and per-client coalescing; `/api/profile`; frontend tick store (per-frame batching), canvas virtualized `Grid`, `Q` (live monitor), `DES`, `QR`, `GP` (lightweight-charts, indicators in a Web Worker, compare, log, crosshair, keyboard pan/zoom), `PERF GRID/CHART` load views |
| 4 Workspace | SQLite migrations 3-4 (`layouts`, `history`), `backend/openterm/userdata.py`, `/api/layouts[/{name}]` GET/PUT/DELETE, `/api/cmdhistory` GET/POST; `LAYOUT`/`MONITOR` `SAVE|LOAD|DEL name` (bare name = LOAD, bare `LAYOUT` = list panel with J/K, Enter, Del-twice, S), `Ctrl+S` (re-save current named layout, else prompts) / `Ctrl+O` (prompts `LAYOUT LOAD ` with name autocomplete), layout name in the status bar; command history moved to SQLite (batched writes, `sendBeacon` on exit, one-time upload of the old localStorage history); Playwright tests for layouts, history and Ctrl+Shift+Arrows resizing; bench gate for layout load |

## Next: Phase 5 (spec BUILD PLAN)
WL watchlists, N news (RSS / GDELT), WEI, MOV, FX/FXC, CRYP (CoinGecko/Binance), CMDTY.
Watchlists are user data: store them in SQLite next to layouts (new migration + `userdata.py`), not localStorage.

Then phases 6-10 in order:
- 6: FA via SEC EDGAR XBRL company facts (needs `SEC_USER_AGENT`), FIL filings, HDS/OWN.
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

## Risks / open items
- Yahoo endpoints are unofficial (stream, spark, chart, quoteSummary crumb flow) and can break without notice. Non-US symbols have no zero-key fallback yet.
- Market-hours lights ignore holidays.
- If the backend is down at page load, command history starts empty for that session (it is not
  re-fetched on reconnect); new commands are still kept and uploaded once the backend answers.
- The CI workflow has never run (no remote). Bench timing on GitHub runners is untested.
- Shell scripts `scripts/setup` and `scripts/dev` are untested on macOS/Linux.

## How to look at the app
Run `.\scripts\dev.ps1`, then open http://localhost:5173. To get a screenshot without the preview pane,
run a small Playwright script against a production build (`npx vite preview --port 4173 --host 127.0.0.1`).
The pattern is in `frontend/e2e/*.spec.ts`. Current look: `docs/screenshot-phase3.png`.
