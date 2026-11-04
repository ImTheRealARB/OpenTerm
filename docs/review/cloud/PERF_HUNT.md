# Perf hunt (cloud, 2026-11-04)

No bench was run (another session owns it); numbers below are build sizes and unit tests only.

## Changes
1. **Startup bundle: help drawer, welcome card and tour are separate chunks.**
   `frontend/src/gui/LazyGui.tsx` (new) loads them with a plain `import()` (no React.lazy/Suspense), preloads each when idle,
   and loads at once when its state opens. `gui/index.ts` and `gui/Overlays.tsx` use the wrappers.
   Entry chunk gzip 123.61 KB -> 121.02 KB (-2.6 KB); raw 374.86 -> 366.72 KB. Chunks: HelpDrawer 2.1, Tour 1.5, Welcome 0.8 KB gz.
   Initial JS+CSS total (what the bench counts) should drop by the same ~2.6 KB from 125.8 KB; still above main's 120.0 KB (+3.2 KB left).
2. **Idle preload staggered.** `main.tsx` used to start ~88 chunk downloads in one idle callback. `functions/idlePreload.ts` (new, pure,
   vitest `idlePreload.test.ts`) now loads 3 per idle slot. Not measured (needs a browser run): expected effect is less main-thread
   and network competition with the first keystrokes and first quote fetch. All chunks still get warmed.

Checks: `tsc` clean, vitest 589 pass, Playwright `beginner.spec.ts` 11 pass and `gui-shell.spec.ts` pass (one earlier failure was port 8000 contention with the bench).

## Verified already fixed on this branch (no change needed)
- `LivePrice` subscribes per symbol (commit 27ab3df).
- `useLiveRows`: symbol index cached (`cachedIndex`), age redraw skips hidden tabs (`startAgeRedraw`) in `functions/liveRowsCore.ts`.

## Not done / rejected
- Moving `settings/commands`, `alertArgs`, `portfolioArgs`, `sectors` out of the entry (~3 KB gz): `execute.ts` calls them synchronously,
  making command submit async risks keystroke-to-paint and e2e timing. Needs a bench to justify.
- `alerts.ts` must stay (alerts are evaluated app-wide from first tick).
- Indicator-toggle chart rebuild: ChartView effect rewrite broke GP e2e before (docs/review/REVERTED.md).
- Not reached: Grid/ticks per-frame allocation audit, screener compression, backend cached-route overhead (no budget left; need bench/browser).

## Data-oriented rewrite (method update): not started, design only
Target: `state/ticks.ts` (`live`/`pending` Maps keyed by symbol, a fresh `changed` Set per frame) -> `liveRowsCore.hitRows` (Map lookup, new `hit` array per tick) -> `Grid.redrawRows`.
Plan: intern each symbol once to an int id (rule 2); `Float64Array` price/change/pct; dirty ids as a `Uint32Array` bitset (rule 5) reused every frame (rule 4);
`useLiveRows` keeps an `Int32Array` id -> row position. Touches `TickListener`'s `ReadonlySet<string>` signature used by LivePrice, alerts, quoteRows, Board, PORT,
so it is a cross-cutting change that needs a browser tick-to-pixel measurement (bench is the other agent's) and a full e2e run. Left undone rather than done unmeasured.

## Data-oriented tick path (2026-11-04)

Rewrote `net/socket.ts` -> `state/ticks.ts` -> `functions/quoteRows.ts` / `liveRowsCore.ts` -> `components/Grid.tsx` as struct-of-arrays.
New modules: `state/symbols.ts` (interning), `state/bitset.ts` (Uint32Array bitsets).

Rules applied (each is commented where it is used):
- **Struct-of-arrays.** `live.price[id]`, `live.change[id]`, ... are Float64Arrays indexed by symbol id (NaN = "tick did not carry it"); pending values, the raw-tick copy for alerts (`RawTicks`) and the per-frame batch (`TickBatch.ids`) are typed arrays too. No row/tick objects.
- **Interning.** A symbol string becomes a small integer once (`symId`), at the two edges only: decoding a WebSocket frame and laying out a grid. Subscription refcounts (`socket.ts`) are an `Int32Array` by id; grid cells read `live.x[rowId(row)]` (the id is cached on the row, `QRow.sid`). No Map/Set keyed by symbol string on the tick, flush or paint path.
- **No CPU memo caches.** `cachedIndex`/`sameLayout`/`hitRows` are gone; the row index (`head`/`next` chained arrays, `buildRowIndex`) is rebuilt on `rows` change, which costs a few typed-array writes.
- **Zero steady-state allocation.** All buffers are preallocated and grow by doubling (`ensure`, `RawTicks.reserve`); the per-frame `Set`, hit array, `flashed` array, two closures per frame (`afterPaint`, `rAF`) were replaced by one reused `TickBatch`, a dirty bitset, a flash bitset with one prebuilt callback, and a 16-slot ring of timestamps with two prebuilt callbacks. Listener lists are arrays walked by index (no Set iterator).
- **Bitsets.** The batch's changed set, the grid's dirty rows and the one-frame highlight rows are bitsets; `Grid.redrawDirty` tests only the visible rows and clears the bitset.
- Still allocating (unavoidable here): `JSON.parse` of each text frame (the server sends JSON), and the strings `fillText` needs for each repainted cell.

Same behaviour: `onRawTicks` still runs per message before batching (alerts); the gauge `series.tickToPixel` still measures oldest buffered tick -> after the frame is painted; `ws.ticksPerSec` / `ws.msgsPerSec` unchanged; the `.grid .sr` mirror is untouched.

API changes (all callers migrated): `TickListener = (batch: TickBatch, frame) => void` (was `ReadonlySet<string>`): LivePrice, GP, GIP, FXC, PORT, `useLiveRows`. `RawTickListener = (ticks: RawTicks) => void`: `command/alerts.ts`. `GridHandle.redrawRows(Iterable<number>)` became `redrawDirty(bitset, frame)`. Removed `state/tickMerge.ts` (its merge rule now lives in `ingest`, tested in `ticks.dod.test.ts`).
**Adapter kept:** `getLive(symbol)` (a per-symbol view object with getters over the arrays, created once per symbol) still serves GP, GIP, LivePrice, FXC, PORT, which read one symbol per frame; grid columns do not use it.

Micro-benchmark `state/ticks.bench.test.ts` (old code copied into the test; `TICK_BENCH_FULL=1 npx vitest run src/state/ticks.bench.test.ts`; default run is a short smoke). 200 symbols, 67 ticks per 60 fps frame = 4,000 ticks/s for 10 s (600 frames), and 60 frames of 4,000 ticks. Per frame = ingest + flush + find rows + visible-dirty loop (canvas drawing not included). Cloud box, Node, one run:

| load | old median / p95 | new median / p95 | old alloc | new alloc |
|---|---|---|---|---|
| steady, 67 ticks/frame | 21.7 / 80.2 us | 12.2 / 94.1 us | 24.4 KB/frame | 0.8 KB/frame (measurement noise) |
| burst, 4,000 ticks/frame | 332.7 / 504.1 us | 278.3 / 458.1 us | 86.2 KB/frame | 0.8 KB/frame |

Medians are ~1.2-1.8x faster; the p95 is dominated by JIT/GC jitter on this shared machine (old p95 includes its GC pauses; new has none from this path). Allocation is the real win: heap growth per frame measured from a forced GC over 5-frame batches. NOT measured here: the browser bench (`tick-to-pixel`, owned by the other agent); run `node scripts/bench.mjs` before/after to confirm "Tick received to pixel p95" does not regress.

Tests: tsc clean, vitest 597 pass, full Playwright 242 pass / 3 fail: `gui-panels` welcome-card focus and `phase17` DLVR are flaky on the base commit too (pass/fail alternating over 4 reruns there), `phase12` BT EDIT belongs to the concurrent BT work.
