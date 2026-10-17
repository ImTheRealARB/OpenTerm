# Handoff

_Last updated: 2026-10-17, end of session 1._

## Where things stand
- **Phases 1-3 of 10 are built and verified.** Phases 1 and 2 are committed (`736d6d5`, `3815fdd`).
  **Phase 3 is NOT committed**: 54 changed or new files in the working tree. Run all the checks below,
  then commit when the user approves.
- Branch `main`, no git remote. The git identity (ankithrbharadwaj) is set for this repo only.
- Latest verification of the uncommitted tree:
  - Backend: 37 pytest passed, ruff clean.
  - Frontend: 19 vitest passed, tsc clean, 10 Playwright passed.
  - Bench: 16/16 budgets PASS.

## Done
| Phase | Contents |
|---|---|
| 1 Scaffold | Shell UI (top bar, command line, clock + market lights, status bar), tiling workspace (split/close/focus/resize/maximize, panel history), command parser `[N:] SEC [MKT] FN [ARGS]`, fuzzy autocomplete, history, `keybindings.json`, PERF HUD/panel, `scripts/bench.mjs`, CI workflow |
| 2 Data core | Provider adapters (Yahoo, Nasdaq), router with fallback + circuit breaker, token buckets, LRU + SQLite WAL cache, SWR envelopes `{data, source, as_of, age_s, stale, fallback_from}`, request coalescing, `/api/quote|history|search|sources|log`, fixture mode, `SOURCES` and `LOG` screens, live ticker search with prefetch |
| 3 First functions | Yahoo protobuf streamer (hand-decoded), REST poll fallback, SYNTHETIC load stream, hub with one upstream subscription per symbol and per-client coalescing; `/api/profile`; frontend tick store (per-frame batching), canvas virtualized `Grid`, `Q` (live monitor), `DES`, `QR`, `GP` (lightweight-charts, indicators in a Web Worker, compare, log, crosshair, keyboard pan/zoom), `PERF GRID/CHART` load views |

## Next: Phase 4 (workspace)
Mostly built already in phase 1. What remains:
1. Named layouts: `LAYOUT SAVE|LOAD|DEL name` (and `MONITOR` alias), `Ctrl+S` / `Ctrl+O` (currently show an info message).
   Persist in SQLite: add a migration in `backend/openterm/db.py` (tables `layouts`, `history`), add `/api/layouts` CRUD,
   and move command history from localStorage to SQLite (spec: persistence in SQLite).
2. Mouse-free panel resizing exists (Ctrl+Shift+Arrows moves the nearest divider). Verify it with a Playwright test.
3. Spec cross-check: `Ctrl+[`/`Ctrl+]` panel history (done), `F5` refresh (done in Q/GP/DES), maximize (done).
4. Run the bench, record Phase 4 numbers in `docs/PERFORMANCE.md`, then update this file.

Then phases 5-10 in order (spec BUILD PLAN):
- 5: WL watchlists, N news (RSS / GDELT), WEI, MOV, FX/FXC, CRYP (CoinGecko/Binance), CMDTY.
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

## Risks / open items
- Yahoo endpoints are unofficial (stream, spark, chart, quoteSummary crumb flow) and can break without notice. Non-US symbols have no zero-key fallback yet.
- Market-hours lights ignore holidays.
- The CI workflow has never run (no remote). Bench timing on GitHub runners is untested.
- Shell scripts `scripts/setup` and `scripts/dev` are untested on macOS/Linux.

## How to look at the app
Run `.\scripts\dev.ps1`, then open http://localhost:5173. To get a screenshot without the preview pane,
run a small Playwright script against a production build (`npx vite preview --port 4173 --host 127.0.0.1`).
The pattern is in `frontend/e2e/*.spec.ts`. Current look: `docs/screenshot-phase3.png`.
