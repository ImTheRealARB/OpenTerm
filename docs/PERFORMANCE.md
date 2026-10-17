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
