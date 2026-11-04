/**
 * Micro-benchmark: OLD tick path (object rows + Maps + a Set per frame) vs NEW (struct-of-arrays, ids, bitsets).
 * The old implementation is a COPY kept only here, for comparison (the app no longer contains it).
 *
 * What one "frame" measures: decode/ingest of the frame's ticks + the flush that applies them + the listener that finds the
 * grid rows to repaint + the grid's "which rows are dirty and visible" loop (canvas drawing itself is not measured; it is the
 * same in both). Timings are per frame, in microseconds. The allocation proxy is bytes of heap allocated per frame
 * (heapUsed delta over short batches that start right after a forced GC) and the number of GC runs.
 *
 * Load: 200 symbols x 20 ticks/s for 10 s, delivered as 60 frames/s (about 67 ticks per frame), then bursts of 4,000 ticks in one frame.
 * Default run is SHORT (a smoke check that both paths agree and the table prints). For the real numbers run:
 *   TICK_BENCH_FULL=1 npx vitest run src/state/ticks.bench.test.ts     (about a minute: it forces a GC between batches)
 */
import { beforeAll, describe, expect, it } from "vitest";
import { buildRowIndex, markHits, rowIds } from "../functions/liveRowsCore";
import { bitHas } from "./bitset";

type Row = [string, number, number | null, number | null, number | null, number | null, number | null, number, string];

// ---------------------------------------------------------------- OLD implementation (copy of the pre-rewrite code)
interface OldLive { price: number; change: number | null; pct: number | null; volume: number | null; high: number | null; low: number | null; t: number; src: string; dir: -1 | 0 | 1; frame: number }
function carryNulls(prev: (number | string | null)[] | undefined, next: (number | string | null)[]): void {
  if (!prev) return;
  for (let i = 2; i <= 6; i++) if (next[i] == null && prev[i] != null) next[i] = prev[i];
}
const oldLive = new Map<string, OldLive>();
const oldPending = new Map<string, Row>();
const oldListeners = new Set<(changed: ReadonlySet<string>, frame: number) => void>();
const oldRaw = new Set<(rows: readonly Row[]) => void>();
let oldFrame = 0;
function oldIngest(rows: Row[]): void {
  for (const r of rows) {
    carryNulls(oldPending.get(r[0]), r);
    oldPending.set(r[0], r);
  }
  for (const l of oldRaw) l(rows);
}
function oldFlush(): void {
  oldFrame++;
  const changed = new Set<string>();
  for (const [sym, r] of oldPending) {
    let e = oldLive.get(sym);
    if (!e) {
      e = { price: r[1], change: r[2], pct: r[3], volume: r[4], high: r[5], low: r[6], t: r[7], src: r[8], dir: 0, frame: oldFrame };
      oldLive.set(sym, e);
    } else {
      e.dir = r[1] > e.price ? 1 : r[1] < e.price ? -1 : e.dir;
      e.price = r[1];
      if (r[2] != null) e.change = r[2];
      if (r[3] != null) e.pct = r[3];
      if (r[4] != null) e.volume = r[4];
      if (r[5] != null) e.high = r[5];
      if (r[6] != null) e.low = r[6];
      e.t = r[7];
      e.src = r[8];
      e.frame = oldFrame;
    }
    changed.add(sym);
  }
  oldPending.clear();
  for (const l of oldListeners) l(changed, oldFrame);
}
function oldHitRows(index: ReadonlyMap<string, number[]>, changed: Iterable<string>): number[] {
  const hit: number[] = [];
  for (const s of changed) {
    const idx = index.get(s);
    if (idx) for (const i of idx) hit.push(i);
  }
  return hit;
}

// ---------------------------------------------------------------- load generator (seeded, so both paths see the same ticks)
// No @types/node here, so Node modules come from process.getBuiltinModule (see CLAUDE.md "vitest blanks CSS imports").
interface NodeProc {
  env: Record<string, string | undefined>;
  memoryUsage(): { heapUsed: number };
  getBuiltinModule(id: string): unknown;
}
const proc = (globalThis as unknown as { process: NodeProc }).process;
const FULL = !!proc.env.TICK_BENCH_FULL;
const STEADY_FRAMES = FULL ? 600 : 60; // 600 frames = 10 s at 60 fps
const BURST_FRAMES = FULL ? 60 : 10;
const SYMS = 200;
const names: string[] = Array.from({ length: SYMS }, (_, i) => `SYN${String(i).padStart(4, "0")}`);
function makeFrames(nFrames: number, ticksPerFrame: number, seed: number): Row[][] {
  let x = seed;
  const rnd = () => ((x = (x * 1664525 + 1013904223) >>> 0) / 4294967296);
  const px = new Float64Array(SYMS).fill(100);
  const frames: Row[][] = [];
  for (let f = 0; f < nFrames; f++) {
    const rows: Row[] = [];
    for (let i = 0; i < ticksPerFrame; i++) {
      const s = Math.floor(rnd() * SYMS);
      px[s] += (rnd() - 0.5) * 0.2;
      const full = rnd() < 0.3; // 70% of ticks carry only the price (the other fields are null)
      rows.push([names[s], px[s], full ? 0.1 : null, full ? 0.1 : null, full ? 1000 : null, full ? px[s] + 1 : null, full ? px[s] - 1 : null, f, "s"]);
    }
    frames.push(rows);
  }
  return frames;
}

// ---------------------------------------------------------------- measuring
/** A `gc()` function: enable V8's --expose-gc at runtime, then fetch `gc` from a fresh VM context. */
const gcFn = (() => {
  (proc.getBuiltinModule("node:v8") as { setFlagsFromString(f: string): void }).setFlagsFromString("--expose-gc");
  return (proc.getBuiltinModule("node:vm") as { runInNewContext(c: string): unknown }).runInNewContext("gc") as () => void;
})();

interface Result { medianUs: number; p95Us: number; bytesPerFrame: number }
function stats(times: number[], bytes: number[]): Result {
  const t = [...times].sort((a, b) => a - b);
  const b = [...bytes].sort((a, c) => a - c);
  return { medianUs: t[t.length >> 1] * 1000, p95Us: t[Math.floor(t.length * 0.95)] * 1000, bytesPerFrame: b[b.length >> 1] };
}
/** Run `frames` through `runOne`; time each frame, and measure heap growth over batches of BATCH frames that follow a forced GC. */
function measure(frames: Row[][], runOne: (rows: Row[]) => void): Result {
  const times: number[] = [];
  const bytes: number[] = [];
  const BATCH = 5;
  for (let i = 0; i + BATCH <= frames.length; i += BATCH) {
    gcFn();
    const h0 = proc.memoryUsage().heapUsed;
    for (let j = 0; j < BATCH; j++) {
      const t0 = performance.now();
      runOne(frames[i + j]);
      times.push(performance.now() - t0);
    }
    const d = proc.memoryUsage().heapUsed - h0;
    if (d >= 0) bytes.push(d / BATCH); // a negative delta means a scavenge ran inside the batch: discard
  }
  return stats(times, bytes.length ? bytes : [0]);
}

const rafQueue: (() => void)[] = [];
let T: typeof import("./ticks");
let S: typeof import("./symbols");
beforeAll(async () => {
  const g = globalThis as unknown as Record<string, unknown>;
  g.window = globalThis;
  g.requestAnimationFrame = (cb: () => void) => rafQueue.push(cb);
  T = await import("./ticks");
  S = await import("./symbols");
});

const VISIBLE_TOP = 0;
const VISIBLE = 40; // rows on screen of a 200-row grid

describe("tick path, old vs new", () => {
  it("per-frame cost and allocation", () => {
    const steady = makeFrames(STEADY_FRAMES, 67, 1); // 10 s of 60 fps frames at 4,000 ticks/s
    const bursts = makeFrames(BURST_FRAMES, 4000, 2);
    const steadyOld = makeFrames(STEADY_FRAMES, 67, 1); // identical content; the old path mutates its rows (carryNulls), so it gets its own copy
    const burstsOld = makeFrames(BURST_FRAMES, 4000, 2);

    // OLD wiring: the grid's index is a Map<string, number[]> and the hit list is a fresh array per frame, plus the old
    // Grid.redrawRows' `flashed` array and rAF closure.
    const oldIndex = new Map<string, number[]>(names.map((s, i) => [s, [i]]));
    let oldPainted = 0;
    oldListeners.add((changed, frame) => {
      const hit = oldHitRows(oldIndex, changed);
      if (!hit.length) return;
      const flashed: number[] = [];
      for (const i of hit) {
        if (i >= VISIBLE_TOP && i < VISIBLE_TOP + VISIBLE) oldPainted++; // drawRow: only visible rows paint
        flashed.push(i);
      }
      if (flashed.length && frame >= 0) rafQueue.push(() => flashed.forEach((i) => i));
    });

    // NEW wiring: id-based CSR index, dirty bitset, one scan of the visible rows.
    const index = buildRowIndex(rowIds(names));
    let newPainted = 0;
    const off = T.onTicks((batch) => {
      if (markHits(index, batch.ids, batch.count) === 0) return;
      for (let i = VISIBLE_TOP; i < VISIBLE_TOP + VISIBLE; i++) if (bitHas(index.dirty, i)) newPainted++;
      index.dirty.fill(0);
    });
    const runNew = (rows: Row[]) => {
      T.ingest(rows, 0);
      const q = rafQueue.splice(0);
      for (const cb of q) cb();
    };
    const runOld = (rows: Row[]) => {
      oldIngest(rows);
      oldFlush();
      rafQueue.length = 0;
    };

    // warm up both (JIT), then measure each twice and keep the better run to reduce noise from this busy machine
    for (let k = 0; k < (FULL ? 2 : 1); k++) {
      measure(makeFrames(60, 67, 9), runOld);
      measure(makeFrames(60, 67, 9), runNew);
    }
    const best = (a: Result, b: Result): Result => (a.medianUs <= b.medianUs ? a : b);
    const twice = (frames: Row[][], again: () => Row[][], run: (rows: Row[]) => void): Result =>
      FULL ? best(measure(frames, run), measure(again(), run)) : measure(frames, run);
    const oSteady = twice(steadyOld, () => makeFrames(STEADY_FRAMES, 67, 1), runOld);
    const nSteady = twice(steady, () => makeFrames(STEADY_FRAMES, 67, 1), runNew);
    const oBurst = twice(burstsOld, () => makeFrames(BURST_FRAMES, 4000, 2), runOld);
    const nBurst = twice(bursts, () => makeFrames(BURST_FRAMES, 4000, 2), runNew);
    off();

    const row = (label: string, o: Result, n: Result) =>
      `${label.padEnd(26)} old median ${o.medianUs.toFixed(1).padStart(8)} us  p95 ${o.p95Us.toFixed(1).padStart(8)} us  alloc ${(o.bytesPerFrame / 1024).toFixed(1).padStart(7)} KB/frame | ` +
      `new median ${n.medianUs.toFixed(1).padStart(8)} us  p95 ${n.p95Us.toFixed(1).padStart(8)} us  alloc ${(n.bytesPerFrame / 1024).toFixed(1).padStart(7)} KB/frame`;
    console.log(["", row("steady 67 ticks/frame", oSteady, nSteady), row("burst 4000 ticks/frame", oBurst, nBurst)].join("\n"));

    expect(oldPainted).toBeGreaterThan(0);
    expect(newPainted).toBeGreaterThan(0);
    expect(S.symCount()).toBeGreaterThanOrEqual(SYMS);
    // The new path must not be slower than the old one (generous bound: this test shares the CPU with other suites).
    if (FULL) {
      expect(nSteady.medianUs).toBeLessThan(oSteady.medianUs * 1.5);
      expect(nBurst.medianUs).toBeLessThan(oBurst.medianUs * 1.5);
    }
  }, 120_000);
});
