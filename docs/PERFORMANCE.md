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

### Phase 17 bench (2026-11-03, branch `claude/opus-phase-17-mcp-alerts-06250f`, Windows)
MCP server, alert delivery and daily brief. No new budgets (delivery runs as a background task after the trigger route answers; DLVR and BRIEF lazy-load). Full gate ALL PASS
(pytest 1694, e2e 223, 149.6 s). Bench run with `OPENROUTER_API_KEY` unset, right after the gate, on a busy machine.

| Run | Tree | Result | Misses |
|---|---|---|---|
| 1 | Phase 17 | 34 / 37 | BT open to paint 124.6 ms, plus 2 others |
| 2 | Phase 17 | 32 / 37 | tick-to-pixel 78.5 ms, frame under load 33.4 ms, keystroke echo 20.1 ms, J frame 50.7 ms, BT 10-year 733 ms |
| 3 | baseline `d1041b4` (no Phase 17 code), same load | 32 / 37 | tick-to-pixel 60.9 ms, chart pan 33.4 ms, BT 10-year 593 ms, BT open 115 ms, IMAP paint 29.3 ms |

Result: the baseline misses as much as Phase 17 under the same load, and the missed rows change from run to run, so the misses are machine load, not this change.
Bundle 119.7 KB gz on the baseline (budget 400 KB). Optional: one bench on a quiet machine for a clean 37/37 record.

### Strategy editor bench (2026-11-03, branch `claude/strategy-editor-part-3-588d90`, Windows)
CodeMirror 6 in `BT EDIT`, loaded by a dynamic `import()` inside the editor (its own chunk, never preloaded). Sizes (gzip): startup bundle 119.9 KB before and after;
BT chunk 13.1 KB to 13.9 KB (template list); new `codeEditor` chunk 125.9 KB, fetched only when an editor opens. Gate ALL PASS (pytest 1708, e2e 226). `OPENROUTER_API_KEY` unset.
Baseline = `20b5bd0` (Phase 17, no editor change) in `C:\otbase`, runs alternated on a busy machine.

| Run | Tree | Result | Misses |
|---|---|---|---|
| 1 | editor | 35 / 37 | tick-to-pixel 53.1 ms, BT 10-year 308 ms |
| 2 | baseline | 36 / 37 | BT 10-year 301.6 ms |
| 3 | editor | 29 / 37 | frame under load 33.4, keystroke echo 20.7, layout load 100.6, chart pan 33.4, BT 10-year 461, BT open 130.7, SEAS 21.5 ms, +1 |
| 4 | baseline, same load | 29 / 37 | tick-to-pixel 76.1, frame under load 33.4, keystroke echo 17.5, chart pan 33.4, BT 10-year 695, BT open 117.9, SEAS 29.6, IMAP 24.9 ms |

Result: the baseline misses as much under the same load; none of the missed rows run editor code (the BT open line paints a cached run, not the editor). Machine load, not this change.

## Cloud baseline 2026-11-04 (Linux cloud box, 4 vCPU, untouched `origin/main` 23082cb)

Gate: pytest 1708, e2e 226, vitest 508/509 (the `corrMath` 20x5y timing test read 328 ms vs 100 under the parallel gate; 69 ms alone). ruff, tsc clean.
Bench run 1: 36/37 (miss: BT result open to first paint). Runs 2 and 3 crashed in the Phase 15 quant section (`quant risk run was served from the cache`), so they printed no table (the bench prints at the end). Investigated in Part 2.
**On this box the bench gate is "no budget worse than this baseline beyond noise"**; absolute budgets were set on Windows.

| Line | Run 1 | Budget | Status |
|---|---|---|---|
| Initial JS+CSS bundle (gzip) | 120.0 KB | 400 KB | PASS |
| Backend p95, cached /api/health | 0.8 ms | 20 ms | PASS |
| Backend p95, cached /api/quote | 0.7 ms | 20 ms | PASS |
| Backend p95, cached /api/history | 2.1 ms | 20 ms | PASS |
| Cold start to usable command line (web) | 129.1 ms | 1500 ms | PASS |
| Cold start, GUI mode (new-user default) | 120.2 ms | - | INFO |
| Keystroke to echo p95 (keydown to next frame) | 14.8 ms | 16.7 ms | PASS |
| Command submit to first paint, cached, p95 | 28.8 ms | 100 ms | PASS |
| Frame time p95, 8-panel workload | 16.7 ms | 20 ms | PASS |
| Command submit to first paint, cold network, p95 | 17.1 ms | 400 ms | PASS |
| Tick received to pixel p95, streaming load | 45.0 ms | 50 ms | PASS |
| Frame time p95, streaming load | 16.8 ms | 20 ms | PASS |
| Keystroke echo p95, streaming load | 15.9 ms | 16.7 ms | PASS |
| Long tasks (>50 ms), streaming load | 0.0 | 0 | PASS |
| JS heap, 9 panels + 200 streaming symbols | 7.5 MB | 500 MB | PASS |
| Ticks delivered to the page per second | 3992.5 /s | - | INFO |
| Layout load to paint p95 (SQLite, 9 / 1 panels) | 70.5 ms | 100 ms | PASS |
| Frame time p95, 10k-row grid scroll | 16.7 ms | 20 ms | PASS |
| Frame time p95, 50k-bar chart pan/zoom | 16.8 ms | 20 ms | PASS |
| Job J frame received to paint p95 | 38.0 ms | 50 ms | PASS |
| Job submit p95, server-side (new + cached) | 7.0 ms | 20 ms | PASS |
| Job submit to first J frame painted p95 | 61.1 ms | - | INFO |
| Cached job (same hash) p95, server-side | 1.7 ms | 20 ms | PASS |
| JOBS / APIKEYS open to first paint p95 | 29.9 ms | 100 ms | PASS |
| Worker pool cold start (first job done) | 93.8 ms | - | INFO |
| BT 10-year daily rule run p95, server-side | 293.9 ms | 300 ms | PASS |
| BT cached run (same hash) p95, server-side | 19.0 ms | 20 ms | PASS |
| BT result open to first paint p95 | 133.4 ms | 100 ms | FAIL |
| BT first run, cold worker (pandas import) | 977.8 ms | - | INFO |
| BT 100 symbols x 10 years | 1985.3 ms | - | INFO |
| RISK 20 names x 3 years p95, server-side | 48.2 ms | 400 ms | PASS |
| PORT OPT HRP 20 names p95, server-side | 12.3 ms | 400 ms | PASS |
| PORT OPT RP 20 names p95, server-side | 17.1 ms | 400 ms | PASS |
| CORR REGIME 20 names x 2 years p95, server-side | 67.9 ms | 300 ms | PASS |
| ALPHA SYN 100 names x 2 years, server-side | 900.6 ms | 8000 ms | PASS |
| AI request to first SSE event p95, server-side | 3.7 ms | 60 ms | PASS |
| AI panel open to first paint p95 | 19.9 ms | 100 ms | PASS |
| Pattern scan (candles + SMC) 5,000 bars p95 | 10.0 ms | 40 ms | PASS |
| SEAS MONTH+WOY+DOM 10,000 daily bars p95 | 12.2 ms | 15 ms | PASS |
| Drawing hit test, 200 drawings p95 | 0.3 ms | 1 ms | PASS |
| IMAP treemap layout, 5,000 tiles p95 | 5.2 ms | 30 ms | PASS |
| SECF fuzzy rank, 7,000 names, per query p95 | 11.9 ms | 25 ms | PASS |
| IMAP canvas paint, 5,000 tiles p95 | 9.4 ms | 16 ms | PASS |

## Cloud session end 2026-11-04 (after Parts 1-4, same box as the cloud baseline)

Gate: ALL PASS (pytest 1726, vitest 586, e2e 245; `node scripts/gates.mjs --keep-going --e2e-last`).
Bench, 6 runs after the work (the second run no longer crashes: the bench killed only the shell, so its backend stayed on port 8000 and the next run reused it).

| Line | Baseline | After (range of runs) | Budget | Note |
|---|---|---|---|---|
| Initial JS+CSS bundle (gzip) | 120.0 KB | 125.8 KB | 400 KB | +5.8 KB: GUI Part 1 about +4.2 KB (cap 5 KB), Part 4 terminal conventions +1.6 KB |
| BT result open to first paint p95 | 133.4 ms | 121-151 ms (p50 96-107) | 100 ms | failed on the baseline too |
| SEAS MONTH+WOY+DOM 10,000 bars p95 | 12.2 ms | 15.5-22 ms (46 ms before the fix) | 15 ms | the time-zone fix used Intl per bar (46 ms); UTC fast path restores it. Side-by-side in vitest old 7.9 ms vs new 7.7 ms median, so what is left is one-shot noise |
| BT 10-year rule run p95 | 293.9 ms | one run 343.5 ms, others pass | 300 ms | known throttling line (CLAUDE.md) |
| 50k-bar chart pan/zoom frame p95 | 16.8 ms | one run 33.3 ms, others pass | 20 ms | known lone-miss line (CLAUDE.md) |

Every other line passed in every run, within noise of the baseline.

## Performance pass 2026-11-04 (data-oriented rewrite, same cloud box)

Method (user's): data-oriented design, struct-of-arrays, flat arrays indexed by interned symbol ids instead of hash tables, no CPU memo caches (redesign instead), no per-frame/per-tick allocation, bitsets instead of bool arrays. Backend provider/SWR/job caches are kept: they protect upstream rate limits and STALE labelling.
Changes: SEAS integer day math + per-call UTC-offset transition table; BT result labels paint before the chart (chart one frame later); tick path = typed arrays + interned ids + dirty-row bitset, zero steady-state allocation (vitest: 21.7 -> 12.2 us/frame, 24.4 -> ~0 KB/frame); help/welcome/tour out of the entry chunk; post-paint preloads staggered. Notes: `docs/review/cloud/PERF_FIXES.md`, `PERF_HUNT.md`.
Bench: run 1 **37/37 PASS** (first clean run on this box), run 2 36/37 (Job J frame to paint 93.8 ms once; 31.9 ms in run 1).

| Line | Cloud baseline (main) | After run 1 | After run 2 | Budget |
|---|---|---|---|---|
| Initial JS+CSS bundle (gzip) | 120.0 KB | 124.8 KB | 124.8 KB | 400 KB |
| Backend p95, cached /api/health | 0.8 ms | 0.7 ms | 0.7 ms | 20 ms |
| Backend p95, cached /api/quote | 0.7 ms | 0.6 ms | 0.7 ms | 20 ms |
| Backend p95, cached /api/history | 2.1 ms | 1.8 ms | 2.1 ms | 20 ms |
| Cold start to usable command line (web) | 129.1 ms | 120.0 ms | 121.6 ms | 1500 ms |
| Cold start, GUI mode (new-user default) | 120.2 ms | 118.1 ms | 120.1 ms | - |
| Keystroke to echo p95 (keydown to next frame) | 14.8 ms | 15.4 ms | 15.7 ms | 16.7 ms |
| Command submit to first paint, cached, p95 | 28.8 ms | 18.8 ms | 20.4 ms | 100 ms |
| Frame time p95, 8-panel workload | 16.7 ms | 16.8 ms | 16.8 ms | 20 ms |
| Command submit to first paint, cold network, p95 | 17.1 ms | 15.9 ms | 12.3 ms | 400 ms |
| Tick received to pixel p95, streaming load | 45.0 ms | 41.7 ms | 43.2 ms | 50 ms |
| Frame time p95, streaming load | 16.8 ms | 16.8 ms | 16.7 ms | 20 ms |
| Keystroke echo p95, streaming load | 15.9 ms | 14.8 ms | 16.0 ms | 16.7 ms |
| Long tasks (>50 ms), streaming load | 0.0 | 0.0 | 0.0 | 0 |
| JS heap, 9 panels + 200 streaming symbols | 7.5 MB | 6.1 MB | 8.4 MB | 500 MB |
| Ticks delivered to the page per second | 3992.5 /s | 4040.6 /s | 4057.8 /s | - |
| Layout load to paint p95 (SQLite, 9 / 1 panels) | 70.5 ms | 58.8 ms | 71.1 ms | 100 ms |
| Frame time p95, 10k-row grid scroll | 16.7 ms | 16.7 ms | 16.7 ms | 20 ms |
| Frame time p95, 50k-bar chart pan/zoom | 16.8 ms | 16.8 ms | 16.8 ms | 20 ms |
| Job J frame received to paint p95 | 38.0 ms | 31.9 ms | 93.8 ms | 50 ms |
| Job submit p95, server-side (new + cached) | 7.0 ms | 7.1 ms | 7.1 ms | 20 ms |
| Job submit to first J frame painted p95 | 61.1 ms | 52.4 ms | 113.3 ms | - |
| Cached job (same hash) p95, server-side | 1.7 ms | 1.3 ms | 1.3 ms | 20 ms |
| JOBS / APIKEYS open to first paint p95 | 29.9 ms | 26.0 ms | 26.1 ms | 100 ms |
| Worker pool cold start (first job done) | 93.8 ms | 66.4 ms | 85.6 ms | - |
| BT 10-year daily rule run p95, server-side | 293.9 ms | 275.3 ms | 289.2 ms | 300 ms |
| BT cached run (same hash) p95, server-side | 19.0 ms | 5.0 ms | 5.7 ms | 20 ms |
| BT result open to first paint p95 | 133.4 ms | 39.6 ms | 35.8 ms | 100 ms |
| BT first run, cold worker (pandas import) | 977.8 ms | 840.3 ms | 930.9 ms | - |
| BT 100 symbols x 10 years | 1985.3 ms | 1825.3 ms | 1687.9 ms | - |
| RISK 20 names x 3 years p95, server-side | 48.2 ms | 50.5 ms | 52.6 ms | 400 ms |
| PORT OPT HRP 20 names p95, server-side | 12.3 ms | 10.3 ms | 9.1 ms | 400 ms |
| PORT OPT RP 20 names p95, server-side | 17.1 ms | 20.0 ms | 19.1 ms | 400 ms |
| CORR REGIME 20 names x 2 years p95, server-side | 67.9 ms | 59.5 ms | 64.0 ms | 300 ms |
| ALPHA SYN 100 names x 2 years, server-side | 900.6 ms | 899.0 ms | 925.8 ms | 8000 ms |
| AI request to first SSE event p95, server-side | 3.7 ms | 4.3 ms | 3.1 ms | 60 ms |
| AI panel open to first paint p95 | 19.9 ms | 18.1 ms | 26.5 ms | 100 ms |
| Pattern scan (candles + SMC) 5,000 bars p95 | 10.0 ms | 9.7 ms | 10.1 ms | 40 ms |
| SEAS MONTH+WOY+DOM 10,000 daily bars p95 | 12.2 ms | 13.4 ms | 11.6 ms | 15 ms |
| Drawing hit test, 200 drawings p95 | 0.3 ms | 0.3 ms | 0.3 ms | 1 ms |
| IMAP treemap layout, 5,000 tiles p95 | 5.2 ms | 4.2 ms | 4.1 ms | 30 ms |
| SECF fuzzy rank, 7,000 names, per query p95 | 11.9 ms | 11.9 ms | 15.0 ms | 25 ms |
| IMAP canvas paint, 5,000 tiles p95 | 9.4 ms | 10.2 ms | 10.1 ms | 16 ms |

## Bundle under 120 KB + SEAS allocation-free core (2026-11-04, same cloud box)
- Startup JS+CSS: 124.8 -> **119.5 KB gz** (main: 120.0). Moves: Vite modulepreload JS dependency lists dropped from the entry (-2.2 KB; lazy chunks fetch their own imports, idle preload warms them), shortcut sheet + PERF HUD lazy (-1.3), THEME/SETTINGS parser a lazy chunk warmed at idle (-1.0; a command typed before it arrives runs once it loads), ACTION_LABELS split (-0.5), lazy-component CSS moved with its component (-0.3). `docs/review/cloud/PERF_HUNT.md`.
- SEAS core: packed-integer dates (year*512+month*32+day) instead of {y,m,d} objects, counting-sort grouping into one Float64Array instead of number[][] + push. Identical output (all kinds, 3 zones); vitest cold p95 5.7 -> 4.2 ms.
- Bench: run 1 **37/37** (SEAS 10.6 ms), run 2 35/37 (50k-bar chart pan 33.3 ms, the known lone miss; SEAS 17.1 ms: this line swings 10-17 ms between back-to-back runs on 4 vCPU). Cold start 104-114 ms (baseline 129), BT open 42-56 ms (baseline 133).

## Local gate after NEXT_FEATURES (2026-11-05, Windows 11, 20 threads, branch `claude/gui-simple-bugs-sp3hq5`)

First full gate and bench of the NEXT_FEATURES work (`docs/specs/NEXT_FEATURES.md` steps 1-6) on the user's laptop. `OPENROUTER_API_KEY` unset.

**Gate: ALL PASS** with `node scripts/gates.mjs --keep-going --e2e-last`: pytest 1776, vitest 1020, e2e 297, ruff and tsc clean (140 s).
Fully parallel (`--keep-going` without `--e2e-last`), every run failed 1-2 e2e tests, a different set each time, and each passed alone
(BT EDIT T reopens, BT EDIT server refusal, GUI welcome card; plus the `eqsFilter` 10k-row timing vitest, 18.3 ms vs 16, 1020/1020 alone).
Three real failures were found and fixed (tests first):
- **GP pan/zoom lost key presses** (`gp-toggle.spec.ts`, failed every run here, passed on the slower cloud box). lightweight-charts queues
  `setVisibleLogicalRange`/`scrollToPosition` and applies them on its next paint, so presses inside one frame all started from the same stale
  range: 4 Left presses moved 10 bars, not 40. Pre-existing on `main`. `ChartView` now builds each pan/zoom on the range it last requested
  (`pendingRange`, cleared one frame later); pan shifts the range instead of the right offset (same bar spacing).
- **BT EDIT focus retry stole focus after Esc** (`phase12.spec.ts` "T reopens" under load). `CodeBox` refocuses the editor 80 ms after it loads
  (the command line takes focus back after Enter); on a busy machine that landed after the user's Esc, so the next T was typed into the code.
  Pre-existing on `main`. The retry now skips once Esc was pressed in the box. New test: "the editor's delayed focus retry does not pull focus
  back after Esc" (Playwright paused clock; red without the fix).
- **"tech stocks under 50 dollars" ignored the price** (manual smoke; the spec's own example). `50 dollars` / `20 usd` now read as `$50`
  (`eqsNatural.ts readNumber`; 4 new vitest cases).

**Bench (run alone): run 1 37/37, run 2 36/37, run 3 37/37.** The run-2 miss was the 50k-bar chart pan frame at 33.4 ms (one dropped frame at
p95, the known lone-miss value also seen on `main`); runs 1 and 3 read 16.7 ms with the same code. Startup bundle 119.9 KB gz (< 120; cloud 119.89).

| Line | Cloud perf pass, run 1 | Local run 1 | Local run 3 | Budget |
|---|---|---|---|---|
| Initial JS+CSS bundle (gzip) | 124.8 KB | 119.9 KB | 119.9 KB | 400 KB |
| Backend p95, cached /api/health | 0.7 ms | 1.2 ms | 1.2 ms | 20 ms |
| Backend p95, cached /api/quote | 0.6 ms | 1.0 ms | 1.1 ms | 20 ms |
| Backend p95, cached /api/history | 1.8 ms | 3.0 ms | 3.1 ms | 20 ms |
| Cold start to usable command line (web) | 120.0 ms | 100.2 ms | 114.0 ms | 1500 ms |
| Cold start, GUI mode (INFO) | 118.1 ms | 96.4 ms | 100.2 ms | - |
| Keystroke to echo p95 | 15.4 ms | 14.6 ms | 14.8 ms | 16.7 ms |
| Command submit to first paint, cached, p95 | 18.8 ms | 18.0 ms | 17.8 ms | 100 ms |
| Frame time p95, 8-panel workload | 16.8 ms | 16.8 ms | 16.7 ms | 20 ms |
| Command submit to first paint, cold network, p95 | 15.9 ms | 17.4 ms | 12.5 ms | 400 ms |
| Tick received to pixel p95, streaming load | 41.7 ms | 39.9 ms | 36.8 ms | 50 ms |
| Frame time p95, streaming load | 16.8 ms | 16.8 ms | 16.8 ms | 20 ms |
| Keystroke echo p95, streaming load | 14.8 ms | 10.0 ms | 9.0 ms | 16.7 ms |
| Long tasks (>50 ms), streaming load | 0.0 | 0.0 | 0.0 | 0 |
| JS heap, 9 panels + 200 streaming symbols | 6.1 MB | 7.8 MB | 8.1 MB | 500 MB |
| Layout load to paint p95 | 58.8 ms | 57.3 ms | 46.8 ms | 100 ms |
| Frame time p95, 10k-row grid scroll | 16.7 ms | 16.7 ms | 16.7 ms | 20 ms |
| Frame time p95, 50k-bar chart pan/zoom | 16.8 ms | 16.7 ms | 16.7 ms (run 2: 33.4) | 20 ms |
| Job J frame received to paint p95 | 31.9 ms | 37.3 ms | 34.9 ms | 50 ms |
| Job submit p95, server-side | 7.1 ms | 4.4 ms | 3.9 ms | 20 ms |
| Cached job p95, server-side | 1.3 ms | 2.0 ms | 2.1 ms | 20 ms |
| JOBS / APIKEYS open to first paint p95 | 26.0 ms | 21.9 ms | 22.2 ms | 100 ms |
| BT 10-year daily rule run p95, server-side | 275.3 ms | 246.5 ms | 234.0 ms | 300 ms |
| BT cached run p95, server-side | 5.0 ms | 7.4 ms | 6.1 ms | 20 ms |
| BT result open to first paint p95 | 39.6 ms | 31.3 ms | 33.3 ms | 100 ms |
| RISK 20 names x 3 years p95 | 50.5 ms | 49.3 ms | 53.7 ms | 400 ms |
| PORT OPT HRP / RP 20 names p95 | 10.3 / 20.0 ms | 9.6 / 14.3 ms | 8.5 / 22.3 ms | 400 ms |
| CORR REGIME 20 names x 2 years p95 | 59.5 ms | 54.6 ms | 78.1 ms | 300 ms |
| ALPHA SYN 100 names x 2 years | 899.0 ms | 693.0 ms | 1493.7 ms | 8000 ms |
| AI request to first SSE event p95 | 4.3 ms | 4.0 ms | 5.6 ms | 60 ms |
| AI panel open to first paint p95 | 18.1 ms | 18.1 ms | 14.4 ms | 100 ms |
| Pattern scan 5,000 bars p95 | 9.7 ms | 5.5 ms | 4.5 ms | 40 ms |
| SEAS MONTH+WOY+DOM 10,000 bars p95 | 13.4 ms | 7.1 ms | 7.9 ms | 15 ms |
| Drawing hit test, 200 drawings p95 | 0.3 ms | 0.2 ms | 0.2 ms | 1 ms |
| IMAP treemap layout, 5,000 tiles p95 | 4.2 ms | 3.3 ms | 3.5 ms | 30 ms |
| SECF fuzzy rank, 7,000 names p95 | 11.9 ms | 8.1 ms | 8.2 ms | 25 ms |
| IMAP canvas paint, 5,000 tiles p95 | 10.2 ms | 7.2 ms | 7.5 ms | 16 ms |

Backend p95 lines read about 1 ms higher than on the Linux cloud box; the Windows review-sprint bench (2026-10-19, above) read cached /api/quote 1.0 ms too, so that is the machine, not this work.

### Wrap-up bench (2026-11-05, branch `claude/wrapup-f02dcc`, Windows, user's app running on :8000 so servers on :8100 / :4273)

Changes since the last full bench: Kite follow-ups, `.BFO` / `.CDS` chains, Kite `1D`, ticker drop detection, the AIS / SHIP / PORTS / DBSRCH / free-data batch. No chart, grid or tick code changed.

| Metric | Run 1 | Run 2 (CPU shared with another session) | Budget |
|---|---|---|---|
| Initial JS+CSS bundle (gzip) | 120.7 KB | 120.7 KB | 400 KB |
| Cold start to usable command line | 121.6 ms | 131.0 ms | 1500 ms |
| Keystroke to echo p95 | 14.7 ms | 14.7 ms | 16.7 ms |
| Command submit to first paint, cached, p95 | 19.0 ms | 18.1 ms | 100 ms |
| Tick received to pixel p95 (200 SYN x 20/s, 9 panels) | 44.2 ms | 55.9 ms (FAIL) | 50 ms |
| Frame time p95, 10k-row grid scroll | 16.7 ms | 16.7 ms | 20 ms |
| Frame time p95, 50k-bar chart pan/zoom | 33.3 ms (FAIL, known lone miss) | 33.3 ms (FAIL) | 20 ms |
| BT 10-year daily run p95, server-side | 276.8 ms | 455.6 ms (FAIL) | 300 ms |
| SEAS 10,000 bars p95 | 9.5 ms | 22.4 ms (FAIL) | 15 ms |
| JS heap, 9 panels + 200 symbols | 6.7 MB | 11.5 MB | 500 MB |
| Backend p95, cached /api/quote | 1.0 ms | 1.1 ms | 20 ms |

Run 1: 36 of 37 (only the chart pan line). Run 2: 33 of 37; the BT, SEAS and tick lines moved together, the pattern of a busy machine (another session was building at the time). A third run was cut short by a pause. A clean rerun on a quiet machine is still to do; the other 31 lines passed in both runs.
Gates the same day: pytest 2032, vitest 1107, Playwright 304 pass (2 specs needed a fixture backend or a test fix, see HANDOFF.md "Wrap-up job").

**Run 3 (clean, 2026-11-05, branch `claude/wrapup-final` = main `49c0fd6` + wrapup):** machine rested 100 s, `OPENROUTER_API_KEY` unset, ports free: **37 of 37 PASS**. Cold start 94.5 ms (web), tick-to-pixel p95 36.8 ms, 50k-bar chart pan 16.7 ms, BT 10-year run 283.2 ms (budget 300; it reads 230 rested and rises after back-to-back runs, so it is the closest line to its budget). The README `## Built to be fast` cells are updated from this run.

**Run 4 (main `f3f183c` = MAP merged, 2026-11-05 night, `OPENROUTER_API_KEY` unset):** gate: ruff, tsc, vitest, pytest 2234 pass; e2e 335 pass plus one `flt` CSV-export flake that passes alone. Bench: the first run (straight after the gate) missed one line, BT 10-year 338.5 ms (budget 300) with cold start 115.3 ms and tick-to-pixel 41.3 ms; after a 150 s rest it was **37 of 37**: cold start 97.3 ms, tick-to-pixel 36.8 to 37.7 ms, 50k-bar pan 16.8 ms, BT 10-year 193.6 ms. Runs 3 and 4 agree within noise, so the README table is unchanged except that BT reads 0.19 to 0.28 s depending on how warm the machine is (the README states the higher figure).

## GUI redesign pass 2 (2026-11-05, Windows 11, 20 threads, idle machine, port 8000 free)
- Bench: **37/37 PASS** on the first run. Startup bundle 121.7 KB gz (budget 400).
- Full gate: ruff, tsc, pytest 2234, vitest all pass; Playwright 337/340 on the first run. Two failures were tests written
  for the old GUI (fixed), one passed alone (flaky).
- Worker counts, each measured twice back to back:

| Suite | Setting | Run 1 | Run 2 | Failures |
|---|---|---|---|---|
| pytest | `-n 6` | 82 s | 80 s | 0 |
| pytest | `-n 10` | 68 s | 67 s | 0 |
| Playwright | 4 workers | 65 s | 66 s | 0, then 1 |
| Playwright | 6 workers | 56 s | 57 s | 1, then 1 |

Decision: pytest moves to `-n 10` (faster, green). Playwright stays at 4 workers: 6 is about 10 s faster but failed a test in both runs.

## Phase 20 swarm engine, 30 presets, skills (2026-11-05, Windows 11, 20 threads, branch `claude/openterm-phase-20-cont-5dddee`)
Nothing in Phase 20 touches a hot path (presets, skills and the swarm engine load on first use). Full gate: ALL PASS in 147 s (pytest 2638, ruff, tsc, vitest, e2e 342).
Bench: **37 pass, 0 fail** (AI request to first SSE event p95 28.4 ms of 60; AI panel open 19.2 ms of 100). No budget regressed.
Update after the server-side alert engine and delivery retry were added (hub tick-listener hook): full gate ALL PASS in 131 s (pytest 2696, ruff, tsc, vitest, e2e 344). Bench: first run 35/37 (50k-bar pan 33.4 ms and BT run 311 ms, both throttling noise after back-to-back runs), rerun **37/37** (tick to pixel 42.5 ms of 50, pan 16.7 ms of 20, BT 246 ms of 300).

## Phase 20 finish: HOME page, ticker tape, VIA, pairing, filings, news (2026-11-05, Windows 11, 20 threads, branch `claude/openterm-phase-20-cont-5dddee`)
Full gate: ALL PASS in 138 s (pytest 2803, ruff, tsc, vitest, e2e 350). The first run had 6 e2e failures: 2 were real (`phase10` compares the saved settings exactly and the e2e seed now saves `startup: "layout"`; fixed in the spec) and 4 passed alone (known e2e flake).
Bench: **37 pass, 0 fail** on the first run (cold start 96.9 ms of 1500, layout load 49.1 ms of 100, 50k-bar pan 16.7 ms of 20, tick to pixel 36.6 ms of 50, BT 10-year 190 ms of 300).
Initial JS+CSS bundle: **123.3 KB gz** (121.7 KB after GUI pass 2): +1.6 KB for the `startup` setting, the tape hook in `App.tsx` / `main.tsx` and the Phase 20 settings. HOME, the tape bar and the ticker tape are lazy chunks. Under the 400 KB budget, above the informal 120 KB goal.

## Audit fixes (2026-11-06, Windows 11, 20 threads, branch `claude/audit-fixes-resume-bbe676`, 8 commits on `main` 2b4396f)
**E-1 (every router returns through orjson, no `jsonable_encoder`)**, in-process TestClient, realistically sized payloads, median of 15:

| Route | Payload | Before | After |
|---|---|---|---|
| `/api/history` 10Y daily | 2,520 bars, 124 KB | 10.6 ms | 1.0 ms |
| `/api/history` deep intraday | 50,000 bars, 2.4 MB | 203.4 ms | 10.4 ms |
| `/api/screener` | 7,000 rows, 492 KB | 45.6 ms | 1.7 ms |

**G-3:** two new bench budgets, read from each answer's `server-timing` header: `/api/history` 10Y daily (real AAPL recording, 268 KB) 1.2-2.2 ms of 20,
`/api/screener` (476-row fixture) 0.6-1.0 ms of 20. The bench now has 39 budgets.

**Bench, like for like** (each after a 60 s rest and no full gate first; benching right after a full gate also failed the streaming and 50k-pan lines,
on this branch only because only this branch was benched that way):

| Line | `main` 2b4396f | branch 02ba643 | Budget |
|---|---|---|---|
| BT 10-year daily rule run p95 | 197.5 ms | **517.4 ms FAIL** | 300 |
| Layout load to paint p95 | 54.5 ms | **119.8 ms FAIL** | 100 |
| Job J frame received to paint p95 | pass | **56.8 ms FAIL** | 50 |
| Tick to pixel, streaming load | 37.5 ms | 42.5 ms | 50 |
| Frame time, 50k-bar pan | 16.7 ms | 16.8 ms | 20 |
| AI request to first SSE event | 24.7 ms | 24.6 ms | 60 |
| Total | 37/37 | 36/39 | |

**Regression ruled out by bisect (2026-11-06 evening).** The 02ba643 column above was a slow machine, not slow code. Each commit was
checked out and benched back to back, 60 s rest before each, no gate first, OPENROUTER_API_KEY unset:

| Commit | BT 10-year run p95 | Layout load p95 | J frame to paint p95 | Total |
|---|---|---|---|---|
| `main` 2b4396f | 198.4 ms | 62.1 ms | **54.6 ms FAIL** | 35/37 |
| ffe3a25 D-1..D-5 | 177.6 ms | 52.3 ms | 33.2 ms | 37/37 |
| 9d3a86c A-1..A-4, B-2 | 173.7 ms | 54.6 ms | 29.2 ms | 37/37 |
| 848470a B-1, B-3..B-5 | 178.8 ms | 52.9 ms | 29.5 ms | 37/37 |
| c409e49 C-1..C-3 | 174.4 ms | 53.2 ms | 32.7 ms | 37/37 |
| 7f3a374 F-1..F-4, E-3, E-4 | 171.1 ms | 51.4 ms | 33.0 ms | 37/37 |
| e3c2570 F-1 follow-up | 176.5 ms | 55.5 ms | 30.7 ms | 37/37 |
| aabf64a E-1, E-2 | 175.2 ms | 54.1 ms | 36.9 ms | 37/37 |
| 02ba643 G-1..G-4 | 171.8 ms | 52.8 ms | 33.9 ms | 39/39 |

No commit moves any of the three lines. `main` (the first bench of the sequence) itself missed J frame (54.6 ms) and SEAS (28.1 ms of 15) once.
The 517 / 120 / 56.8 ms numbers were the machine (see CLAUDE.md "Bench throttling"), not the code.
**Final (02ba643 code + the DLVR test fix):** full gate ALL PASS (pytest 2881, ruff, tsc, eslint, vitest, e2e 352/352), then 60 s rest and bench
**39/39**: BT 10-year run 180.0 ms, layout load 52.5 ms, J frame to paint 27.6 ms, 50k-bar pan 16.8 ms, AI first SSE event 32.5 ms.
The DLVR e2e race (`phase17.spec.ts`, ~1 in 6 on `main`) is fixed: each Space press now waits up to 1 s for its PUT before retrying, so a press that
registered is never repeated (24/24 with `--repeat-each=6`).
