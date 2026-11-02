# Performance

Budgets are enforced by `scripts/bench.mjs` (run in CI; any FAIL breaks the build). Rows marked N/A
need features from later phases and turn into hard gates as soon as those land.

## How each budget is measured

| Budget | Method |
|---|---|
| Initial bundle < 400 KB gz | gzip of every JS/CSS file referenced by `dist/index.html` |
| Cold start < 1.5 s | `performance.now()` at the first painted frame (`openterm:ready` mark), p95 of 5 fresh browser contexts |
| Keystroke echo < 1 frame | keydown `event.timeStamp` to the next `requestAnimationFrame`. The native input value is already updated, so that frame paints it. Autocomplete runs in a React transition and cannot delay it. |
| Command to paint (cached) < 100 ms | `performance.mark` at submit; the target panel reports its content committed; measured after the next paint |
| Frame time | rAF deltas while the frame sampler is on. Gate is p95 < 20 ms: at 60 Hz every frame is 16.7 ms, so a p95 at 16.7 is perfect and >25 ms means a dropped frame |
| Backend p95 < 20 ms | server-side time from the ASGI timing middleware (`/api/perf`). Client time is printed as a note |

### Measurement notes (decisions, not loosened budgets)

- **Keystroke echo is gated at 16.7 ms (one 60 Hz frame), not 16.0.** Keydown-to-next-frame includes the
  wait for vsync, which is uniform over 0-16.7 ms, so its p95 sits near 16 ms regardless of code speed.
  Missing the next frame pushes it past 16.7 ms, so real regressions still fail.
- **Backend latency is gated server-side.** Node's `fetch` on Windows loopback adds ~15.6 ms
  (the Windows timer tick) per request. A keep-alive Python client measured p50 0.55 / p95 0.69 ms
  against the same server, and server-side p95 is 0.3 ms.

## Results log

### Phase 1 (2026-10-17, Windows 11, headless Chromium 156, 1920x1080)

| Metric | Value | Budget | Status |
|---|---|---|---|
| Initial JS+CSS (gzip) | 78.4 KB | 400 KB | PASS |
| Backend p95 /api/health (server) | 0.3 ms | 20 ms | PASS |
| Cold start to command line | 80.5 ms | 1500 ms | PASS |
| Keystroke echo p95 | 15.8 ms | 16.7 ms | PASS |
| Command to paint, cached, p95 | 16.9 ms | 100 ms | PASS |
| Frame p95, 8 panels | 16.8 ms | 20 ms | PASS |
| JS heap, 8 panels | 5.9 MB | 500 MB | PASS |

### Phase 2 (2026-10-17, same machine; backend in fixture mode)

| Metric | Value | Budget | Status |
|---|---|---|---|
| Initial JS+CSS (gzip) | 79.4 KB | 400 KB | PASS |
| Backend p95 cached /api/health | 0.4 ms | 20 ms | PASS |
| Backend p95 cached /api/quote (3 symbols) | 0.8 ms | 20 ms | PASS |
| Backend p95 cached /api/history (AAPL 1Y, 251 bars) | 2.5 ms | 20 ms | PASS |
| Cold start to command line | 83.8 ms | 1500 ms | PASS |
| Keystroke echo p95 | 15.2 ms | 16.7 ms | PASS |
| Command to paint, cached, p95 | 16.3 ms | 100 ms | PASS |
| Frame p95, 8 panels | 16.7 ms | 20 ms | PASS |
| JS heap, 8 panels | 6.0 MB | 500 MB | PASS |

Live network (not gated; real Yahoo from India, keep-alive client): first `AAPL 1Y` history 231 ms
then 1.9 ms cached; 6-symbol batch quote 687 ms cold then 1.3 ms; search 648 ms cold.
Search is the slowest cold path, so autocomplete shows functions and recent symbols instantly
and merges search hits when they arrive (80 ms debounce, stale replies dropped).

### Phase 3 (2026-10-17, same machine; fixtures + SYNTHETIC stream, 300 ms simulated upstream)

| Metric | Value | Budget | Status |
|---|---|---|---|
| Initial JS+CSS (gzip) | 81.5 KB | 400 KB | PASS |
| Backend p95 cached /api/health, /api/quote, /api/history | 0.3 / 0.5 / 1.4 ms | 20 ms | PASS |
| Cold start to command line | 77.5 ms | 1500 ms | PASS |
| Keystroke echo p95 (idle / under streaming load) | 14.4 / 10.0 ms | 16.7 ms | PASS |
| Command to paint, cached, p95 | 16.0 ms | 100 ms | PASS |
| Command to paint, cold network (skeleton), p95 | 18.0 ms | 400 ms | PASS |
| Tick received to pixel p95 (200 symbols x 20/s, 9 panels) | 35.6 ms | 50 ms | PASS |
| Frame p95: 8 panels / streaming / 10k-row grid scroll / 50k-bar chart pan | 16.8 / 16.7 / 16.8 / 16.7 ms | 20 ms | PASS |
| Long tasks during streaming load | 0 | 0 | PASS |
| JS heap, 9 panels + 200 streaming symbols | 4.8 MB | 500 MB | PASS |
| Ticks delivered to the page | 4,020/s of 4,000/s offered | info | — |

Notes:
- **9 panels, not 10.** Panels are numbered 1-9 for focus-by-number, so 9 is the UI maximum.
  The load is still the specified 200 symbols x 20 ticks/s (4,000 ticks/s).
- **Memory is JS heap** (`performance.memory`), not whole-process RSS. Canvas backing stores and the
  browser itself are not included. A whole-process number needs the desktop build (phase 10).
- Tick-to-pixel is measured from WebSocket receive to *after* the frame is painted, for the oldest
  tick in each frame (the worst case), so it includes up to one frame of batching by design.

### Phase 4 (2026-10-17, same machine; fixtures + SYNTHETIC stream)

| Metric | Value | Budget | Status |
|---|---|---|---|
| Initial JS+CSS (gzip) | 83.4 KB | 400 KB | PASS |
| Backend p95 cached /api/health, /api/quote, /api/history | 0.4 / 0.6 / 1.8 ms | 20 ms | PASS |
| Cold start to command line | 80.7 ms | 1500 ms | PASS |
| Keystroke echo p95 (idle / under streaming load) | 14.9 / 10.3 ms | 16.7 ms | PASS |
| Command to paint, cached / cold network, p95 | 15.5 / 16.8 ms | 100 / 400 ms | PASS |
| Tick received to pixel p95 (200 symbols x 20/s, 9 panels) | 37.2 ms | 50 ms | PASS |
| Frame p95: 8 panels / streaming / 10k-row grid / 50k-bar chart | 16.7 / 16.8 / 16.8 / 16.7 ms | 20 ms | PASS |
| Long tasks during streaming load | 0 | 0 | PASS |
| JS heap, 9 panels + 200 streaming symbols | 5.2 MB | 500 MB | PASS |
| **New:** layout load to paint p95 (real backend + SQLite, alternating 9-panel and 1-panel layouts) | 35.5 ms | 100 ms | PASS |

Notes:
- **Layout load is gated at the cached-command budget (100 ms).** The layout lives in local SQLite, so
  it is a cached command that repaints every panel. Measured from submit, through the
  `/api/layouts/{name}` fetch (browser → vite preview proxy → backend), to after the frame that
  shows the new panels. Data inside the panels then loads as usual (skeleton first).
- Entry bundle +1.9 KB gz (81.5 → 83.4): layout commands, layout validation and the SQLite-backed
  history are in the entry chunk because the command line needs them at once. The `LAYOUT` list
  panel is a lazy function module.
- Command history writes are batched (500 ms) and sent off the command path, so running a command
  never waits on the network. Cached command to paint did not move (16.9 → 15.5 ms, noise).

### Phase 5 (2026-10-17, same machine; fixtures + SYNTHETIC stream)

17/17 PASS. Phase 4 numbers in brackets; no budget regressed.

| Metric | Value | Budget | Status |
|---|---|---|---|
| Initial JS+CSS bundle (gzip) | 84.8 KB [83.4] | 400 KB | PASS |
| Backend p95 cached health / quote / history (server-side) | 0.7 / 0.9 / 2.2 ms [0.4 / 0.5 / 1.7] | 20 ms | PASS |
| Cold start to usable command line | 92.5 ms [76.6] | 1500 ms | PASS |
| Keystroke to echo p95 (idle / streaming load) | 14.4 / 10.5 ms [14.2 / 10.4] | 16.7 ms | PASS |
| Command submit to first paint p95 (cached / cold network) | 17.5 / 12.6 ms [16.7 / 17.9] | 100 / 400 ms | PASS |
| Tick received to pixel p95, streaming load | 37.5 ms [35.6] | 50 ms | PASS |
| Frame time p95 (8-panel / streaming / 10k grid / 50k chart) | 16.7 / 16.8 / 16.8 / 16.7 ms | 20 ms | PASS |
| Long tasks (>50 ms), streaming load | 0 | 0 | PASS |
| JS heap, 9 panels + 200 streaming symbols | 6.0 MB [5.3] | 500 MB | PASS |
| Ticks delivered per second (offered 4,000) | 3,992 [3,960] | - | INFO |
| Layout load to paint p95 | 35.8 ms [34.7] | 100 ms | PASS |

Notes:
- Entry bundle +1.4 KB gz (83.4 → 84.8): the `WL` command grammar and watchlist autocomplete live in
  the entry chunk because the command line needs them at once. The eight new panels (N, WL, WEI, MOV,
  FX, FXC, CRYP, CMDTY) and the shared `quoteRows` / `boards` code are lazy function modules.
- The other moves are within run-to-run noise on this machine (sub-millisecond backend p95, cold start
  ±15 ms between runs). The Q refactor onto `quoteRows.ts` did not move tick-to-pixel or frame time.
- Test wall time: pytest now runs on 4 xdist workers (13.1 → 9.3 s; `-n auto` = 20 workers was slower,
  15.3 s, because worker start-up dominates). Playwright runs tests within a file in parallel too.

### Phase 6 (2026-10-17, same machine; fixtures + SYNTHETIC stream)

17/17 PASS. Phase 5 numbers in brackets; no budget regressed.

| Metric | Value | Budget | Status |
|---|---|---|---|
| Initial JS+CSS bundle (gzip) | 85.0 KB [84.8] | 400 KB | PASS |
| Backend p95 cached health / quote / history (server-side) | 0.7 / 0.7 / 1.9 ms [0.7 / 0.9 / 2.2] | 20 ms | PASS |
| Cold start to usable command line | 92.3 ms [92.5] | 1500 ms | PASS |
| Keystroke to echo p95 (idle / streaming load) | 14.4 / 9.8 ms [14.4 / 10.5] | 16.7 ms | PASS |
| Command submit to first paint p95 (cached / cold network) | 18.5 / 18.1 ms [17.5 / 12.6] | 100 / 400 ms | PASS |
| Tick received to pixel p95, streaming load | 38.2 ms [37.5] | 50 ms | PASS |
| Frame time p95 (8-panel / streaming / 10k grid / 50k chart) | 16.7 / 16.7 / 16.7 / 16.7 ms | 20 ms | PASS |
| Long tasks (>50 ms), streaming load | 0 | 0 | PASS |
| JS heap, 9 panels + 200 streaming symbols | 5.1 MB [6.0] | 500 MB | PASS |
| Ticks delivered per second (offered 4,000) | 4,000 [3,992] | - | INFO |
| Layout load to paint p95 | 36.3 ms [35.8] | 100 ms | PASS |

Notes:
- Entry bundle +0.2 KB gz (84.8 → 85.0): only the `secApi` block in `net/api.ts` and the registry lines are in the
  entry chunk. FA, FIL/SEC, OWN, HDS and the shared `secTables` / `secPanel` code are lazy function modules.
- The first bench run reported the 50k-bar chart pan/zoom frame p95 at 33.3 ms (FAIL). Phase 6 changes nothing under
  `chart/` or `components/`; the rerun gave 16.7 ms and 17/17 PASS. Treat a lone chart-pan miss as machine noise and
  rerun once before investigating.
- Tests: 90 pytest (66 + 24 in `test_phase6.py`), 46 vitest, 29 Playwright (23 + 6 in `phase6.spec.ts`).

### Phase 7 (2026-10-17, same machine; fixtures + SYNTHETIC stream)

17/17 PASS on the last two runs. Phase 6 numbers in brackets. This machine was noisier than for Phase 6 (see notes).

| Metric | Value | Budget | Status |
|---|---|---|---|
| Initial JS+CSS bundle (gzip) | 85.4 KB [85.0] | 400 KB | PASS |
| Backend p95 cached health / quote / history (server-side) | 0.5-0.6 / 0.7-0.8 / 2.3 ms [0.7 / 0.7 / 1.9] | 20 ms | PASS |
| Cold start to usable command line | 94-112 ms [92.3] | 1500 ms | PASS |
| Keystroke to echo p95 (idle / streaming load) | 14.3-14.7 / 12.1-15.1 ms [14.4 / 9.8] | 16.7 ms | PASS |
| Command submit to first paint p95 (cached / cold network) | 16.6-17.6 / 15.6-17.7 ms [18.5 / 18.1] | 100 / 400 ms | PASS |
| Tick received to pixel p95, streaming load | 38.5-44.2 ms [38.2] | 50 ms | PASS |
| Frame time p95 (8-panel / streaming / 10k grid / 50k chart) | 16.7-16.8 ms each | 20 ms | PASS |
| Long tasks (>50 ms), streaming load | 0 | 0 | PASS |
| JS heap, 9 panels + 200 streaming symbols | 5.1 MB [5.1] | 500 MB | PASS |
| Ticks delivered per second (offered 4,000) | 3,969-4,026 [4,000] | - | INFO |
| Layout load to paint p95 | 35.5-39.9 ms [36.3] | 100 ms | PASS |

Notes:
- Entry bundle +0.4 KB gz (85.0 → 85.4): `macroApi` in `net/api.ts` and the registry lines. FRED, MACRO, RATES, ERN, ECO and
  `macroUi` / `macroArgs` are lazy function modules.
- Four complete bench runs back to back: the first failed tick-to-pixel (NaN, 0 ticks delivered: the stream did not start), the
  second failed tick-to-pixel (51.7 ms; keystroke under load 15.2 ms) and the 50k-bar chart pan (33.3 ms), the last two were
  17/17. None reproduced and the code on those paths is unchanged by Phase 7 except the optional `readoutLabel` prop on
  `ChartView`. If the streaming gate fails alone, rerun twice before investigating.
- Tests: 116 pytest (90 + 26 in `test_phase7.py`), 66 vitest (46 + 20 `macroArgs`), 40 Playwright (29 + 11 in `phase7.spec.ts`).

### Phase 8 (2026-10-17, same machine; fixtures + SYNTHETIC stream)

17/17 PASS on three consecutive runs. Phase 7 numbers in brackets (ranges where it was noisy).

| Metric | Value | Budget | Status |
|---|---|---|---|
| Initial JS+CSS bundle (gzip) | 89.3 KB [85.4] | 400 KB | PASS |
| Backend p95 cached health / quote / history (server-side) | 0.5 / 0.7 / 1.5 ms [0.5-0.6 / 0.7-0.8 / 2.3] | 20 ms | PASS |
| Cold start to usable command line | 83.5-93.0 ms [94-112] | 1500 ms | PASS |
| Keystroke to echo p95 (idle / streaming load) | 14.9 / 10.0-15.4 ms [14.3-14.7 / 12.1-15.1] | 16.7 ms | PASS |
| Command submit to first paint p95 (cached / cold network) | 17.0 / 13.6 ms [16.6-17.6 / 15.6-17.7] | 100 / 400 ms | PASS |
| Tick received to pixel p95, streaming load | 36.0-45.6 ms [38.5-44.2] | 50 ms | PASS |
| Frame time p95 (8-panel / streaming / 10k grid / 50k chart) | 16.7 ms each | 20 ms | PASS |
| Long tasks (>50 ms), streaming load | 0 | 0 | PASS |
| JS heap, 9 panels + 200 streaming symbols | 5.6-8.8 MB [5.1] | 500 MB | PASS |
| Ticks delivered per second (offered 4,000) | 4,010 [3,969-4,026] | - | INFO |
| Layout load to paint p95 | 35.1-38.5 ms [35.5-39.9] | 100 ms | PASS |

Notes:
- Entry bundle +3.9 KB gz (85.4 → 89.3): the alert engine (`command/alerts.ts`, `AlertFlash`), the PORT / ALRT command
  grammar in `execute.ts` and `portfolios.ts` are in the entry chunk because alerts watch symbols app-wide and the
  command line needs the grammar at once. The PORT and ALRT panels and the portfolio math / CSV code are lazy modules.
- The alert hook runs inside `ticks.ingest` (raw ticks, before frame batching). With no active alerts it is a set lookup per
  tick; tick-to-pixel and frame time did not move beyond the run-to-run spread above.
- Tests: 126 pytest (116 + 10 in `test_phase8.py`), 91 vitest (66 + 25), 46 Playwright (40 + 6 in `phase8.spec.ts`).
- One pytest (`test_core.py::test_stale_while_revalidate`) failed once under 4-worker load and passed on three solo runs and the rerun.

### Phase 9 (2026-10-17, same machine; fixtures + SYNTHETIC stream)

17/17 PASS on four of five runs; one run missed tick-to-pixel (56.1 ms). Phase 8 numbers in brackets.

| Metric | Value | Budget | Status |
|---|---|---|---|
| Initial JS+CSS bundle (gzip) | 90.3 KB [89.3] | 400 KB | PASS |
| Backend p95 cached /api/health (server-side) | 0.6-0.8 ms [0.5] | 20 ms | PASS |
| Cold start to usable command line | 106-255 ms [84-93] | 1500 ms | PASS |
| Keystroke to echo p95 (idle / streaming load) | 14.0-14.8 / 10.8-15.5 ms [14.9 / 10.0-15.4] | 16.7 ms | PASS |
| Command submit to first paint p95 (cached / cold network) | 17.1-17.6 / 11.1-25.3 ms [17.0 / 13.6] | 100 / 400 ms | PASS |
| Tick received to pixel p95, streaming load | 37.0-44.2 ms (one run 56.1 FAIL) [36.0-45.6] | 50 ms | PASS |
| Frame time p95 (8-panel / streaming / 10k grid / 50k chart) | 16.7-16.8 ms each | 20 ms | PASS |
| Long tasks (>50 ms), streaming load | 0 | 0 | PASS |
| JS heap, 9 panels + 200 streaming symbols | 5.7-9.7 MB [5.6-8.8] | 500 MB | PASS |
| Ticks delivered per second (offered 4,000) | 3,959-4,043 [4,010] | - | INFO |
| Layout load to paint p95 | 39.2-48.3 ms [35.1-38.5] | 100 ms | PASS |

Notes:
- Entry bundle +1.0 KB gz (89.3 → 90.3): the `api9` block, the Alt+X export binding (`keybindings.json`, `keys.ts`, `App.tsx`) and
  `tableExport` hook calls pulled into the entry. EQS, HIST, CORR, COMP and `eqsFilter` / `corrMath` / `returns` are lazy modules.
- Cold start, layout load and tick-to-pixel were noisier than in earlier phases (cold start ranged 106-255 ms in back-to-back runs
  with nothing changed between them), so the machine, not Phase 9, is the likely cause: nothing in Phase 9 runs on the cold path.
  The one tick-to-pixel miss (56.1 ms, heap 9.7 MB, layout 48.3 ms in the same run) did not repeat in the next three runs.
- Screener payload is ~1 MB: fetched only when EQS or COMP-fallback opens, cached server-side 15 min, parsed in the browser.
  CORR math is under 1 ms for 20 symbols x 5 y, so there is no worker.
- Tests: 139 pytest (126 + 13 in `test_phase9.py`), 119 vitest (91 + 28), 59 Playwright (46 + 13 in `phase9.spec.ts`).
- CSV-hook wiring of the Phase 6-8 panels (follow-up commit): bundle unchanged at 90.3 KB, bench 17/17 on two more runs (cold start 90-111 ms, tick-to-pixel 36-40 ms); 60 Playwright.
- `test_core.py::test_stale_while_revalidate` flaked twice under 4 xdist workers (50 ms TTL); its TTL is now 0.5 s.

### Phase 10 (2026-10-17, same machine; fixtures + SYNTHETIC stream) and full pass

17/17 PASS on two of three runs; one run missed only the 50k-bar chart pan (33.4 ms) and the next two runs were 16.7-16.8 ms. Phase 9 numbers in brackets.

| Metric | Value | Budget | Status |
|---|---|---|---|
| Initial JS+CSS bundle (gzip) | 95.5 KB [90.3] | 400 KB | PASS |
| Backend p95 cached /api/health (server-side) | 0.6-0.7 ms [0.6-0.8] | 20 ms | PASS |
| Cold start to usable command line | 107-155 ms [90-255] | 1500 ms | PASS |
| Keystroke to echo p95 (idle / streaming load) | 14.4-14.5 / 9.8-13.8 ms [14.0-14.8 / 10.8-15.5] | 16.7 ms | PASS |
| Command submit to first paint p95 (cached / cold network) | 15.7-20.1 / 11.5-14.3 ms [17.1-17.6 / 11.1-25.3] | 100 / 400 ms | PASS |
| Tick received to pixel p95, streaming load | 38.3-41.9 ms [37.0-44.2] | 50 ms | PASS |
| Frame time p95 (8-panel / streaming / 10k grid / 50k chart) | 16.7-16.8 ms (chart pan 33.4 in one run) | 20 ms | PASS |
| Long tasks (>50 ms), streaming load | 0 | 0 | PASS |
| JS heap, 9 panels + 200 streaming symbols | 5.9-7.4 MB [5.7-9.7] | 500 MB | PASS |
| Ticks delivered per second (offered 4,000) | 3,992-4,031 [3,959-4,043] | - | INFO |
| Layout load to paint p95 | 37.8-44.1 ms [39.2-48.3] | 100 ms | PASS |

Notes:
- Entry bundle +5.2 KB gz (90.3 → 95.5): settings runtime / sync, vim state machine, keybinding overrides and the theme list are in the entry chunk
  because the first paint needs the theme and the command line needs vim at once. The SETTINGS panel is a lazy module. 95.5 KB is 24% of the 400 KB budget.
- Settings cost on the cold path: the theme comes from the localStorage mirror before first paint; the `/api/settings` reconcile runs after paint.
  Cold start stayed in the same 90-155 ms spread as earlier phases.
- Tests at the end of Phase 10: 163 pytest (139 + 24 in `test_phase10.py`), 169 vitest (119 + 50), 66 Playwright (60 + 6 in `phase10.spec.ts`).
- Whole-build comparison, Phase 5 → Phase 10: bundle 84.8 → 95.5 KB, tick-to-pixel 37.5 → 38-42 ms, layout load 35.8 → 38-44 ms, frame p95 unchanged at 16.7 ms,
  long tasks 0. No budget regressed; all moves are within the machine's run-to-run spread except the bundle, which grew with 5 phases of features.
- Not measured: Docker image and Tauri shell (neither tool is installed here).

### Post-merge fixes (2026-10-17, same machine, later the same evening)
Panel tab shows the security only for functions that use it; charts skip the volume histogram for series without volume.
163 pytest, 169 vitest, 66 Playwright, tsc + ruff clean. Bench: 15/17 then 16/17. Tick-to-pixel missed on every run
(55.4, 59.3 ms) and also missed (57.6 ms) with both fixes reverted, so the change is the machine, not the code; earlier
the same day it ran 38-42 ms. Chart pan missed once (33.4 ms) and passed on the rerun (16.7 ms), as before. Bundle 95.6 KB.

### Phase 11 baseline (2026-10-18, same machine; before any Phase 11 code, spec step `docs/specs/PHASE_11.md`)
163 pytest, 169 vitest, 66 Playwright, tsc + ruff clean. Bench run 1: 15/17 (tick-to-pixel 60.5 ms, chart pan 33.4 ms);
run 2: **17/17**. Run 2 is the baseline for Phase 11:

| Metric | Value | Budget |
|---|---|---|
| Bundle (gzip) | 95.6 KB | 400 KB |
| Backend p95 health / quote / history (server) | 0.8 / 1.0 / 3.2 ms (run 1) | 20 ms |
| Cold start to command line | 130.0 ms | 1500 ms |
| Keystroke echo p95 (idle / load) | 15.0 / 15.6 ms (run 1) | 16.7 ms |
| Command to paint, cached / cold network | 16.0 / 17.1 ms (run 1) | 100 / 400 ms |
| Tick to pixel p95 | 43.1 ms | 50 ms |
| Frame p95, 50k-bar chart pan | 16.7 ms | 20 ms |
| Layout load p95 | 39.4 ms | 100 ms |
| JS heap, 9 panels + 200 symbols | 9.1 MB (run 1) | 500 MB |

### Phase 11 tests step (2026-10-18; tests only, no app code changed, bundle still 95.6 KB)
164 pytest + 38 strict-xfail, 174 vitest (5 `it.fails`), 70 Playwright (4 `test.fail`), tsc + ruff clean.
Bench 16/17 on both runs, each missing a different known-noisy budget: run 1 long tasks 1 (budget 0; tick-to-pixel 39.6 ms),
run 2 chart pan 33.4 ms (long tasks 0, tick-to-pixel 50.0 ms). Neither can come from this step.

### Phase 11 step 3: key store, redaction, KEY REQUIRED, APIKEYS (2026-10-18)
186 pytest + 16 xfail (steps 4-5), 174 vitest, 70 Playwright, tsc + ruff clean. Bench **17/17** first run: bundle 96.0 KB
(+0.4), backend p95 0.8 / 1.0 / 2.8 ms, cold start 127.8 ms, keystroke 14.6 ms, cached command 16.4 ms, tick-to-pixel 37.9 ms,
long tasks 0, heap 5.6 MB, layout 40.3 ms, chart pan 16.7 ms. `keyring` stays out of startup (loaded 2 s later, off the
event loop). The APIKEYS open budget is added to the bench with JOBS in step 4.

### Phase 11 step 4: job runner, JOBS (2026-10-18)
195 pytest + 7 xfail (step 5), 178 vitest, 70 Playwright, tsc + ruff clean. New bench section G + `jobsBench()`.
First runs gated submit-to-first-frame end to end at 50 ms: 66.8 / 52.6 / 54.1 ms p95 (p50 41.7-46.1). Split: frame
received to paint 34.6 ms p95, the rest is the HTTP POST through the Vite preview proxy (~16 ms Node loopback artifact on
Windows); server time 1.4 ms. The gate was split with the user's OK (frame-to-paint 50 ms, server submit 20 ms, end to end
INFO). Final run **21/21**: bundle 98.0 KB (+2.0, jobs store + frames in the entry: the socket routes `J` frames),
backend p95 0.6 / 0.8 / 1.7 ms, cold start 100.6 ms, keystroke 14.5 ms, cached command 16.9 ms, tick-to-pixel 36.1 ms,
heap 5.2 MB, layout 38.7 ms; job frame-to-paint 33.3 ms, job submit server 2.0 ms, end to end 49.2 ms (INFO), cached job
1.3 ms, JOBS/APIKEYS open 23.0 ms, worker pool cold start 157-207 ms (INFO). Chart pan missed once (33.4 ms) in an earlier
run, as before.

### Phase 11 step 5: LLM gateway (2026-10-19)
205 pytest + 1 xfail (the recorded OpenRouter stream, waiting for the key), 181 vitest, 72 Playwright, tsc + ruff clean.
No new budget: the gateway is imported on first use (`api.llm_of`), so startup is unchanged. Bundle 98.0 KB (unchanged;
the cap edit lives in the lazy APIKEYS chunk). Run 1 missed tick-to-pixel (56.0 ms) and chart pan (33.4 ms); run 2 missed
chart pan only (33.4 ms; an unrelated Astro dev server was using CPU); run 3 **21/21**. Run 2 otherwise: backend p95
0.7 / 1.0 / 2.8 ms, cold start 122.4 ms, keystroke 14.9 ms, cached command 17.3 ms, tick-to-pixel 43.7 ms, heap 5.9 MB,
layout 40.8 ms, job frame-to-paint 31.8 ms, job submit 2.6 ms, cached job 1.9 ms, JOBS/APIKEYS open 24.7 ms. Run 3: chart
pan 16.8 ms, tick-to-pixel 47.0 ms.

### Phase 11 verification (2026-10-19, step 6: docs only, no app code)
205 pytest + 1 xfail (recording), 181 vitest, 72 Playwright, tsc + ruff clean. Bench **21/21 on the first run**: bundle
98.0 KB, backend p95 0.7 / 1.0 / 1.9 ms, cold start 112.0 ms, keystroke 14.8 ms (9.6 ms under streaming load), cached
command 17.0 ms, cold network 15.7 ms, tick-to-pixel 36.2 ms, heap 9.5 MB, layout 41.0 ms, grid scroll 16.8 ms, chart pan
16.8 ms, job frame-to-paint 32.6 ms, job submit 2.1 ms, cached job 1.6 ms, JOBS/APIKEYS open 21.4 ms; INFO: submit to first
J frame 57.4 ms via proxy, pool cold start 220.1 ms. Against the Phase 11 baseline (before any Phase 11 code) every gated
number is inside its budget; the bundle grew 95.6 -> 98.0 KB (jobs store and `J` frame parser in the entry).

### Phase 12 tests step (2026-10-19; tests, fixtures and scripts only, no app code)
206 pytest + 75 xfail (74 Phase 12 + the Phase 11 recording), 187 vitest (6 `it.fails`), 77 Playwright (5 `test.fail`),
tsc + ruff clean. Bench **21/21** first run: bundle 98.0 KB, cold start 113.4 ms, tick-to-pixel 36.1 ms, chart pan 16.8 ms,
worker pool cold start 187.6 ms (INFO).

### Phase 12 step 3: BT engine core, rules, sandbox, API, migration 9 (2026-10-19; backend only)
262 pytest + 19 xfail (18 Phase 12 steps 5-8 + the Phase 11 recording), 187 vitest, 77 Playwright, tsc + ruff clean.
Bench **21/21** first run: cold start 124.8 ms, keystroke echo 14.7 ms, command to paint 17.8 ms, tick-to-pixel 36.2 ms,
streaming frame 16.7 ms, layout load 36.6 ms, job frame-to-paint 27.9 ms, job submit 1.8 ms, cached job 1.7 ms,
JOBS/APIKEYS open 19.5 ms; INFO: worker pool cold start 278.0 ms (was 187.6 ms; not gated).
The BT budgets (10-year run < 300 ms, cached < 20 ms, BT open < 100 ms) are gated from step 4.

### Phase 12 step 4: BT panel, BT bench budgets (2026-10-19)
263 pytest + 19 xfail, 187 vitest, 77 Playwright, tsc + ruff clean. Bench **24/24**: bundle 98.3 KB, cold start 95.0 ms,
tick-to-pixel 36.4 ms, chart pan 16.8 ms; new gates: **BT 10-year rule run 224.2 ms** (< 300, server-side: POST +
job created->finished, n=12), **BT cached run 5.0 ms** (< 20), **BT open to first paint 65.4 ms** (< 100, p50 57, n=20);
INFO: BT cold worker (pandas import) 2.2 s, 100 symbols x 10 years 1.7 s end to end (target < 5 s).
Optimizations found while gating (before -> after):
- **Per-bar row cache in the ported engine** (`BaseEngine._bar_row`): `df.loc[ts]` ran 2-3 times per bar and was half
  the run. Backtest alone 235 -> 177 ms; the Vibe cross-checks still match exactly. BT run gate 299 -> 214-224 ms.
- **Return `Orjson(...)` from big routes.** A plain dict goes through FastAPI's `jsonable_encoder`, which walks every
  equity point (~30 ms for a 10-year run). BT cached POST that embeds the run: 39 -> 5 ms.
- **Cached BT answers carry the run** (no second request) and `BT` in the command line prefetches the BT + chart chunks.
- **ChartView starts its indicator worker on the first indicator request**, so line-only charts (FRED, BT) skip it.
  BT open p95 154 -> 65 ms over all four changes.

Phase 3 optimizations (before → after):
- **React 19 Suspense throttle.** First use of every lazy function cost ~300 ms
  (DES 323 ms, QR 315 ms, GP 318 ms, Q 326 ms) even with the chunk already downloaded: React holds
  revealed Suspense content back for ~300 ms. Function modules now render from a loaded-module map
  with no Suspense. Cold-network command to paint p95: **309.9 ms → 18.0 ms**.
- **Keystroke echo under load measured at frame start.** The callback timing included tick-flush
  work queued earlier in the same frame (17.1 ms, same frame). Now uses the rAF frame-start
  timestamp, which is exactly "the frame that draws the character": 10.0 ms under load.
- **Panel remount key excludes arguments.** A GP timeframe or Q list edit updates in place instead
  of destroying and recreating the chart/grid.
- **Chart chunk (59.5 KB gz) is not idle-preloaded**; it is fetched when `GP` appears in the command
  line (intent prefetch), so the entry bundle stays at 81.5 KB.

Phase 1 optimizations (before → after):
- Cheatsheet overlay moved to a lazy chunk; it was pulled into the entry chunk by a static import (entry 79.2 → 78.4 KB gz).
- Clock writes `textContent` once per second instead of re-rendering React (no measurable cost now; avoids a 1 Hz render of the top bar).

### Phase 12 step 5: engines (India, crypto, forex, futures, composite), Binance candles (2026-10-19)
302 pytest + 11 xfail, 187 vitest, 77 Playwright, tsc + ruff clean. Bench **24/24** first run: bundle 98.3 KB, cold start
90.3 ms, tick-to-pixel 36.9 ms, chart pan 16.7 ms, **BT 10-year rule run 233.2 ms** (< 300; step 4 was 224.2), cached run
4.8 ms, BT open 81.2 ms (< 100; p50 59.9, step 4 65.4); INFO: BT cold worker 4.1 s (step 4: 2.2 s; `import pandas`
alone is 1.5 s on this machine, the six new engine modules add about 10 ms, so the rest is machine noise on a fresh
worktree; re-check at the end of the phase), 100 symbols x 10 years 1.6 s. The history provider order gained
`binance_klines` in front: its `supports()` is one regex, so Yahoo symbols pay nothing measurable (backend p95
cached /api/history 1.9 ms).

### Phase 12 step 6: BT MC / BT WF (2026-10-19)
315 pytest + 9 xfail, 192 vitest, 80 Playwright, tsc + ruff clean. Bench **24/24** on the third run, after two runs that
missed on machine noise with no change in the code they time: run 1 tick-to-pixel 65.7 ms (the streaming path is not
touched by this step); run 2 BT 10-year run 411.5 ms and BT open 100.8 ms (the same metrics read 229.9 / 90.4 on run 1
and 285.6 / 72.1 on run 3; `import pandas` and the 100-symbol run slowed by the same factor in run 2). Run 3: tick-to-pixel
36.5 ms, **BT 10-year rule run 285.6 ms** (< 300; step 5 233.2), cached run 5.2 ms, BT open 72.1 ms (< 100), cold worker
2.2 s, 100 symbols x 10 years 1.6 s. The BT run budget has little headroom on this machine: watch it in steps 7-9.

### Phase 12 step 7: BT RUNS compare, BT EXPORT (2026-10-19)
326 pytest + 6 xfail, 193 vitest, 85 Playwright, tsc + ruff clean. Bench: every gate except one passes (bundle 98.5 KB, tick-to-pixel 36-45 ms, BT cached run 6 ms, BT open 77-88 ms); the BT 10-year rule run read 383 / 493 / 403 / 399 ms on four runs in a row (budget 300; 230 and 286 in steps 5-6) with no change in the run path (step 7 only adds two read-only endpoints). The same in-process engine run measures 160-170 ms cool and 250-320 ms after a dozen back-to-back runs, so the machine is throttling (Google Drive sync is also busy). NOT closed: re-measure on a rested machine at the end of the phase; if it still misses, profile the run path.

### Phase 12 step 8: IMPORT (2026-10-19)
354 pytest + 1 xfail, 196 vitest, 87 Playwright, tsc + ruff clean (`node scripts/gates.mjs`: all five gates in 50 s). Bench not
run for this step: it adds one set lookup (`symbol in service.local.symbols`) to `DataService.history` and a lazy `IMPORT`
panel chunk; the phase bench at step 9 gates `/api/history` and the bundle.

### Phase 12 final: strategy editor, docs, phase bench (2026-10-19)
354 pytest + 1 xfail (the Phase 11 OpenRouter recording), 198 vitest, 92 Playwright, tsc + ruff clean (`node scripts/gates.mjs`: 61 s for all
five). Bench **24/24** on a rested machine, first run: bundle 98.8 KB (Phase 11 end 98.0), cold start 104.6 ms, backend p95 cached
/api/history 2.7 ms, keystroke 14.9 ms, tick-to-pixel 36.9 ms, chart pan 16.7 ms, layout load 33.0 ms; BT: **10-year rule run 233.6 ms**
(< 300), cached 5.1 ms (< 20), open to first paint 69.5 ms (< 100); INFO: cold worker 2.4 s, 100 symbols x 10 years 1.7 s (< 5 s target).
The step-7 misses of the BT run budget (383-493 ms, four runs in a row) were the machine: the same in-process engine run is 160-170 ms
cool and 250-320 ms after a dozen back-to-back runs; after a rest the bench reads 233 ms again. Real-backend smoke run (fixture mode,
Playwright against the built frontend served by the backend): BT, M, W, P, `BT MC <run>`, `BT RUNS` compare, IMPORT then BT and GP on the
imported symbol, `BT EDIT` save + run in the real sandbox, sandbox refusal: all 10 steps pass. It found one bug the mocked tests could not
(Ctrl+K swallowed while a textarea has focus), fixed in IMPORT and the editor.

## Phase 13 bench (2026-10-18, equity research, keyed layer, RT IEX)
24/24 pass, no budget moved. Nothing new runs on the hot path without keys: the IEX poller sleeps on `has_key`, `Hub.emit` adds one `is not None`
test per tick, news merging only runs when a keyed source supports the capability. Tick received to pixel p95 36.8 ms (budget 50), keystroke echo
14.8 ms, 8-panel frame 16.7 ms, BT 10-year run 195.7 ms (budget 300), BT open 82.8 ms (budget 100), initial bundle 101.1 KB gzip (budget 400; the
13 research panels share one `ResearchPanel` and load on demand). The research routes are cached SWR like FA, and a real-backend run answered `CN AAPL`
from live Yahoo headlines with no startup error.

## Test suite speed (2026-10-19, on top of Phase 12 step 4)
Same machine, shared with other sessions running tests, so each figure is a range over 3+ runs. No app code changed.

| Suite | Before | After |
|---|---|---|
| pytest | 263 passed + 19 xfail, 39-41 s (`-n 4`) | 268 passed + 19 xfail, 20-29 s (`-n 6 --dist worksteal`) |
| vitest | 187, 2.1 s (forks) | 187, 1.3-1.6 s (threads) |
| Playwright (`CI=1`, incl. build) | 77, 30-45 s wall | 77, 18-27 s wall |

- **pytest: shared TLS context.** Each app start (`client` fixture, ~300 per run) built an httpx client, and loading
  certifi's CA bundle cost ~0.35 s of its ~0.4 s. `conftest.py` builds the default context once per xdist worker (tests
  never open a TLS connection). Worker time 133 s -> 60 s, of which fixture setup 68 s -> 8 s.
- **pytest: `-n 6 --dist worksteal`.** The job tests (each spawns a worker that imports pandas, ~2 s) bunched up on
  one worker under the default scheduler. `-n 10` was not faster.
- **pytest: merged duplicates, no assertion lost.** Four migration-upgrade tests (userdata v2, phase 5 fresh DB,
  phase 8 v5 + alert columns, phase 11 migration text) -> one test parametrized over every schema version 0-9 (plus a
  check that `TABLES_BY_VERSION` covers every migration). Three "survives restart" tests (history + layouts, watchlists,
  portfolios + alerts) -> one test with 2 app starts instead of 6.
- **pytest flake fixed:** `test_runtime_limits_fail_closed` gave the MEMORY LIMIT and NO SIGNALS cases a 3 s limit that
  also covers the worker's pandas import, so under load they ended as TIME LIMIT. Only the TIME LIMIT case keeps 3 s.
- **Playwright: one page load per test.** Every setup did goto -> `localStorage.clear()` -> reload, but each test already
  gets a fresh browser context. Now `e2e/app.ts` `openApp()` (phase 12's spec left as is while its steps land). Phase 4's
  mid-test "fresh session" still clears storage itself.
- **Playwright web server runs `vite build`, not `npm run build`:** the `tsc --noEmit` inside it (~5 s) is its own gate.

## Phase 14 bench (2026-10-19, options, rates, futures)
24/24 pass on the rested run. First run right after the gates read the BT 10-year rule run at 317 ms (budget 300): throttling, since a rested rerun read 207.5 ms
(Phase 13: 195.7 ms). Tick received to pixel p95 36.3 ms (budget 50; Phase 13 36.8), initial bundle 102.7 KB gzip (Phase 13 101.1; budget 400), keystroke echo
14.7 ms, 8-panel frame 16.7 ms, BT open 63.3 ms. The new panels (OMON, OV, OSA, OVDV, SKEW, HIVG, CT, WIRP, COT, FXFA, YAS, SWPM, CDSW, RATES views) share
`ResearchPanel` and load on demand; chart and heat map render only when opened, so nothing new runs on the hot path. The surface render has no separate budget gate.

## Phase 15 bench (risk, quant library, alphas)
Five new server-side budgets (spec `docs/specs/PHASE_15.md` decision M), so the bench has 24 + 5 = 29 budgets. Measured like the BT budgets: `server-timing` of
`POST /api/quant/{fn}` plus the job's own `created_at` to `finished_at`, on warm workers (concurrent warm-up rounds first), every measured run with a distinct
parameter so none is a cache hit. Data: SYN names in fixture + synthetic mode, a 20-name `BENCH15` portfolio (SYN0000-SYN0019).

| Budget | Limit | Measured | Method |
|---|---|---|---|
| RISK, 20 names x 3 years, p95 | 400 ms | 83.9 ms | n=12, `conf` varies |
| PORT OPT HRP, 20 names, p95 | 400 ms | 12.8 ms | n=12, `rf` varies |
| PORT OPT RP, 20 names, p95 | 400 ms | 33.2 ms | n=12, `rf` varies |
| CORR REGIME, 20 names x 2 years, p95 | 300 ms | 90.9 ms | n=12, `edge` varies |
| ALPHA, SYN 100 names x 2 years, all 29 factors | 8000 ms | 1289.9 ms | n=3 (slowest), `h` varies, after one warm-up scan |

**Result (2026-10-18): 28 of 29 pass.** The one miss is the old BT 10-year rule run: 322.9 ms against 300. The same bench on the Phase 14 commit
(`edb3292`) read **322.3 ms** on the same machine the same hour (a rested run, nothing else running), so the miss is the machine reading slower today than in
earlier phases (195-285 ms rested), not a Phase 15 change; it is recorded, not hidden. Two things the bench found and Phase 15 fixed: (1) `quantBench` polls
`GET /api/jobs/{id}`, which `/api/perf` files under `/api/jobs`, so run before the read it pushed "Job submit p95" from 5.7 ms to 25 ms: the new budgets now run
after that read; (2) four concurrent identical `POST /api/quant/risk` calls raced on the content-addressed data file's temp name and rename on Windows (HTTP 500):
`bt/store.py` `write_data` now uses a unique temp file and tolerates a concurrent replace. The Phase 15 panels share `ResearchPanel` and load on demand, so
nothing new runs on the hot path.

**Rerun (2026-10-18, commit `df5325e`, rested machine): 29 of 29 pass.** BT 10-year rule run 208 ms against 300, so the earlier 323 ms miss was machine throttling, as suspected.
New budgets: RISK 37.0 ms, PORT OPT HRP 7.0 ms / RP 16.6 ms, CORR REGIME 54.9 ms, ALPHA SYN 673.4 ms. Interaction budgets: tick-to-pixel 38.3 ms, keystroke echo 14.5 ms,
frame p95 16.8 ms. Measured before the ALPHA Enter formula line (`info` per row: one docstring read per factor inside the worker, nothing on the hot path); the next gate re-checks ALPHA.

## Phase 16 bench (AI layer)
Two new budgets (spec `docs/specs/PHASE_16.md`, "First-token budget"), so the bench has 29 + 2 = 31. The model's own latency is network and is not gated; these are what this server and panel control.
Fixture mode replays a recorded OpenRouter answer (`llm_tool_turn1.txt` / `llm_tool_turn2.txt`) with a fake key, set through `PUT /api/keys/openrouter` into a memory keyring (the bench never touches the real key store).

| Budget | Limit | Measured | Method |
|---|---|---|---|
| AI request to first SSE event p95, server-side | 60 ms | 1.2 ms | `POST /api/ai/chat` in to first event out (`/api/ai/first_event` in `/api/perf`), n=12, the `start` event leaves before any key, price or model work |
| AI panel open to first paint p95 | 100 ms | 18.0 ms | typed `AI` to painted panel, n=10 |

**Result (2026-10-18, step 2): 30 of 31 pass; the one miss is the old BT 10-year rule run (368 ms and 374 ms in two runs, against 300).** Same-hour control: the Phase 15 commit `df5325e` benched on this machine right after reads
410 ms for BT 10-year, 84.7 ms for RISK and 1247 ms for ALPHA (the rested run recorded above read 208 / 37 / 673 ms), so the machine is throttled today (everything reads about 2x slower) and Phase 16 changes nothing on that path.
Re-bench on a rested machine before calling the phase closed.

**Phase 16 close (2026-10-18, rested machine): 31 of 31 pass.** BT 10-year 191.3 ms (limit 300), AI request to first SSE event p95 8.3 ms (limit 60; it was 1.2 ms before the audit manifest was hashed per request, still far inside), AI panel open to first paint p95 19.4 ms (limit 100), RISK 20 names 35.4 ms, PORT OPT HRP 7.8 ms, keystroke echo 15.0 ms, frame p95 16.8 ms. The earlier BT miss was throttling, as controlled above. SWARM, THESIS, AUDIT and AI AUTO have no latency budget: their cost is the model's own time, and the ledger write happens at the final event.

## Phase 19 bench (charting, discovery, macro, crypto)
New budgets are added per step (spec `docs/specs/PHASE_19.md`). The chart-maths ones run in the page through `PERF CALC` (generated TEST DATA, p95 of 15 runs) so no network or backend is involved.

| Budget | Limit | Measured | Method |
|---|---|---|---|
| Pattern scan (candles + SMC) 5,000 bars p95 | 40 ms | 5.8 ms | `PERF CALC`, `candlePatterns` + `smc` |
| SEAS MONTH + WOY + DOM, 10,000 daily bars p95 | 15 ms | 9.1 ms | `PERF CALC`, three tables |
| Drawing hit test, 200 drawings p95 | 1 ms | 0.2 ms | `PERF CALC`, per call, mixed kinds |
| IMAP treemap layout, 5,000 tiles p95 | 30 ms | 2.9 ms | `PERF CALC`, 12 groups, 1600 x 900 |
| IMAP canvas paint, 5,000 tiles p95 | 16 ms | 4.9 ms | `PERF CALC`, one canvas pass |

**Step 3 (2026-10-18): 36 of 36 pass on the rested rerun.** The first run right after the full gate missed twice: tick received to pixel 59.5 ms (limit 50; the rerun after a minute's rest reads 37.3 ms, the known throttle noise) and the IMAP paint at 17.5 ms (a real miss: one `fillRect` and one fill-style change per tile).
The painter now batches the tile fills into nine colour-band paths (4.9 ms). Step 3 puts a per-tick `TickBuffers.add` on the hub's emit path (three array appends); the streaming budgets did not move (frame p95 16.8 ms, long tasks 0, 4,027 ticks/s delivered of 4,000 offered).

**Steps 7 and 9, Windows (2026-10-18): 36 of 37 pass twice; the one miss is BT 10-year (333 ms, then 415 ms alone; limit 300), and it is machine throttling, not Phase 19.**
Phase 19 changes nothing under `bt/`, `jobs/`, `quant*/` or the backend dependencies since Phase 16 (`git diff fe50765`), and the other server-side quant lines read about 2x their rested values in the same run
(RISK 84.7 ms vs 35-37 rested, the exact reading of the throttled control under Phase 16 above), while every browser line passes: tick to pixel 44.5 ms, streaming frame 16.8 ms, keystroke echo 14.3 ms,
layout load 50.4 ms, 50k-bar pan 16.8 ms, SEAS 9.6 ms, SECF 7.6 ms, IMAP paint 5.1 ms, bundle 108.0 KB, 4,022 ticks/s. Rerun rested (mains power, nothing else running) to see BT under 300 ms again (Phase 16 close: 191 ms).
The earlier Linux-container run (27/37) was on 2-5x slower hardware and is not comparable. Note for Linux runs: `bench.mjs` leaves its backend and `vite preview` running when it exits there; kill them before a second run.

## Review sprint (2026-10-19, micro-benchmarks only; full bench in Phase 2 below if recorded)
Measured with scratch scripts against temp DBs or Node, no servers. Best of N unless noted. The Phase 2 bench has not yet confirmed these end to end.
| Area | Change | Before | After |
|---|---|---|---|
| Cache | `Cache.get_many` used by `DataService.quotes`, 2000 cold keys | 526.8 ms | 11.5 ms |
| Jobs | `JobStore.recent(50)` with ~1 MB results (no blob read, covering index) | 1070 ms | 0.35-0.8 ms |
| World | GIP `bucket()` on a full 20k-tick ring (single pass) | ~24 ms median | 4.2-5.6 ms |
| AI | `doc_search` on a 3M-character document (index built once) | 171 ms median | 3.3 ms |
| AI | AI DOC upload of a 4.9 MB HTML file, worst event-loop stall (parse in thread) | 828 ms | 42 ms |
| Frontend | job frame flush, 300 jobs x 40 frames (one map copy) | 0.614 ms | 0.019 ms |
| Chart | indicator worker request at 50k bars (transferred buffers) | 2.75 ms | 0.97 ms |
Rejected (no gain): `to_thread` for the screener, companyfacts and NSE bhavcopy parsers (GIL).

### Review sprint bench (2026-10-19, Windows, `node scripts/bench.mjs` on `claude/review-all` after the gate)
Run 1 (straight after the full gate, machine throttled): 35 pass, 2 miss: BT 10-year 400.2 ms (budget 300), BT open to first paint 122.1 ms (budget 100). Run 2 after 2 minutes of rest: **37 pass, 0 fail**.
Selected run-2 numbers: cached /api/quote 1.0 ms; tick to pixel p95 36.3 ms (50); job submit 4.8 ms (20); cached job 1.9 ms; BT 10-year 205.6 ms (300); BT cached 6.1 ms; BT open to first paint 90.2 ms (100); RISK 76.3 ms (400); CORR REGIME 92.5 ms (300); ALPHA SYN 881 ms (8000); AI first SSE 4.7 ms (60). No budget regressed; the first-run BT misses match the known throttling note (CLAUDE.md). Gate wall-clock before/after: `docs/review/BASELINE.md`.

### Terminal look bench (2026-10-19, branch `claude/ui-terminal-look`, Windows)
Restyle of the chrome and data views (command field, key-hint row, panel bands, grid rules, chart colours). Full gate ALL PASS (pytest 1628, e2e 183, 123.1 s). Bench: **37 pass, 0 fail**. Grid and tick budgets: frame p95 10k-row grid scroll 16.8 ms (20), tick to pixel p95 36.2 ms (50), command submit to first paint 16.9 ms (100), IMAP paint 5.1 ms (16).

### GUI mode bench (2026-11-02, branch `claude/opus-orchestrator-6b3fee`, Windows)
GUI shell, panel toolbars, help drawer, welcome card, tour and polish of 8 panels. Full gate ALL PASS (pytest 1630, e2e 220, 147.8 s). The 37 budgets run on the
Terminal shell (the bench seeds `mode` = terminal); a new INFO line measures GUI-mode cold start, the new-user default. Run with `OPENROUTER_API_KEY` unset (a key in env makes the fake-key PUT return 409).
Before = terminal-look bench above (2026-10-19). After = second run (rested only briefly: it followed the full gate and a first bench run).

| Metric | Budget | Before | After |
|---|---|---|---|
| Cold start to usable command line (Terminal) | 1500 ms | - | 135.9 ms |
| Cold start, GUI mode (INFO) | - | - | 154.7 ms (first run 129.6 ms vs 125.8 ms Terminal) |
| Command submit to first paint, cached p95 | 100 ms | 16.9 ms | 18.2 ms |
| Frame p95, 10k-row grid scroll | 20 ms | 16.8 ms | 16.7 ms |
| Frame p95, 50k-bar chart pan/zoom | 20 ms | - | 16.8 ms (first run 33.3 ms, known noise) |
| IMAP canvas paint, 5,000 tiles | 16 ms | 5.1 ms | 9.4 ms |
| BT 10-year daily rule run, server-side | 300 ms | - | **500.5 ms FAIL** (first run 717 ms) |

Result: **36 pass, 1 fail.** The BT miss is server-side (job created to finished); this change touches no backend code beyond one settings field, and CLAUDE.md records 230 ms rested vs 380-490 ms
after back-to-back runs. Third run after about 15 minutes of rest: **34 pass, 3 fail** (BT 10-year 697.6 ms; chart pan 33.3 ms; BT result open to first paint 104.3 ms vs 100, p50 77.5,
which passed in both earlier runs with the same code). Cold start Terminal 129.1 ms, GUI 110.1 ms. The machine was not idle: about 23% CPU from other apps (Hermes gateway,
Google Drive, Brave, several `serve.py` servers). **`main` baseline under the same load** (main checkout, commit 85749a8, same code as this branch's base): run 1 **34/37** (BT 10-year 487.7 ms, chart pan 33.4 ms,
tick to pixel 61.7 ms all FAIL; BT open p95 80.0, p50 61.2), run 2 **32/37** (BT 10-year 665.8 ms, BT open p95 123.1 / p50 109.7 FAIL). Branch BT open p50 was 70.9 / 71.7 / 77.5,
inside main's 61-110 spread. **Conclusion: every miss is machine load; GUI mode adds no measurable regression.** A clean 37/37 needs a quiet machine.

| Run (same load) | Score | BT 10-year | BT open p95 / p50 | Chart pan |
|---|---|---|---|---|
| branch run 2 | 36/37 | 500.5 FAIL | 96.7 / 71.7 | 16.8 |
| branch run 3 | 34/37 | 697.6 FAIL | 104.3 / 77.5 FAIL | 33.3 FAIL |
| main run 1 | 34/37 | 487.7 FAIL | 80.0 / 61.2 | 33.4 FAIL |
| main run 2 | 32/37 | 665.8 FAIL | 123.1 / 109.7 FAIL | - |
