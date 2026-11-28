/**
 * Phase 25 bench lines (spec section 7), measured by PERF CALC in the browser and read by `scripts/bench.mjs`:
 *   - a 40-line script over 10,000 bars: full run <= 30 ms (p95)
 *   - 5 scripted studies, one live tick each (updateLast + tick), all five together <= 4 ms (p95)
 *
 * Pure code: it takes the engine's `compile` as an argument, so PERF CALC can load the engine lazily (dynamic import)
 * and vitest can call it directly. The bars are a seeded random walk: TEST DATA, never shown as a security.
 */
import type { compile as compileFn } from "./index";

/** 40 lines that use the common parts: inputs, ta.* calls, var, if / else, a user function, plots, a label, a condition. */
export const BENCH_SOURCE = `indicator("Bench", overlay=false)
len = input.int(14, "RSI length", min=2, max=100)
fastLen = input.int(12, "Fast")
slowLen = input.int(26, "Slow")
sigLen = input.int(9, "Signal")
bbLen = input.int(20, "BB length")
mult = input.float(2.0, "BB mult")
r = ta.rsi(close, len)
[m, s, h] = ta.macd(close, fastLen, slowLen, sigLen)
[mid, up, lo] = ta.bb(close, bbLen, mult)
e1 = ta.ema(close, 10)
e2 = ta.ema(close, 30)
w = ta.wma(close, 15)
hi = ta.highest(high, 20)
lw = ta.lowest(low, 20)
width = (up - lo) / mid
score(x, y) =>
    d = x - y
    d > 0 ? 1 : d < 0 ? -1 : 0
trend = score(e1, e2)
var streak = 0
if trend > 0
    streak += 1
else
    streak := 0
var lastCross = 0.0
if ta.crossover(e1, e2)
    lastCross := close
pos = (close - lw) / math.max(hi - lw, 0.0001)
smooth = ta.sma(pos, 5)
plot(r, "RSI", color = r > 70 ? color.red : r < 30 ? color.green : color.gray)
plot(h, "Hist", style="histogram")
plot(width * 100, "Width")
plot(smooth * 100, "Pos")
plot(streak, "Streak")
hline(70, "Upper")
hline(30, "Lower")
if barstate.islast
    label.new(bar_index, r, str.tostring(math.round(r, 1)))
alertcondition(ta.crossunder(r, 70), "RSI down", "RSI fell below 70")
`;

/** A repeatable random walk of `n` daily bars (seeded, so every run measures the same work). */
export function benchBars(n: number, seed = 7): { o: Float64Array; h: Float64Array; l: Float64Array; c: Float64Array; v: Float64Array; t: Float64Array } {
  const b = { o: new Float64Array(n), h: new Float64Array(n), l: new Float64Array(n), c: new Float64Array(n), v: new Float64Array(n), t: new Float64Array(n) };
  let s = seed;
  const rnd = () => {
    s = (s * 1664525 + 1013904223) % 4294967296;
    return s / 4294967296;
  };
  let px = 100;
  for (let i = 0; i < n; i++) {
    const open = px;
    px = Math.max(1, px * (1 + (rnd() - 0.5) * 0.04));
    b.o[i] = open;
    b.c[i] = px;
    b.h[i] = Math.max(open, px) * (1 + rnd() * 0.01);
    b.l[i] = Math.min(open, px) * (1 - rnd() * 0.01);
    b.v[i] = 1e6 * (0.5 + rnd());
    b.t[i] = 631152000 + i * 86400;
  }
  return b;
}

const p95 = (xs: number[]): number => {
  const s = xs.slice().sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.floor(s.length * 0.95))];
};

export interface BenchResult {
  lines: number;
  bars: number;
  /** p95 of a full run (compile excluded: the chart compiles once) */
  runMs: number;
  /** p95 of one live tick on each of 5 studies */
  tickMs: number;
}

/** Time the two Phase 25 budgets. Throws if the bench script does not compile or errors (a broken bench must not pass). */
export function benchScript(compile: typeof compileFn, bars = 10_000, rounds = 15): BenchResult {
  const c = compile(BENCH_SOURCE);
  if (!c.ok) throw new Error(`BENCH SCRIPT DOES NOT COMPILE: ${c.errors.map((e) => `${e.line}:${e.col} ${e.msg}`).join("; ")}`);
  const cols = benchBars(bars);
  // 2 warm-up runs are not counted (the JIT compiles the engine on the first one; the bench line says so)
  for (let k = 0; k < 2; k++) c.program.run(cols, { chartTimeframe: "1D" });
  const run: number[] = [];
  for (let k = 0; k < rounds; k++) {
    const t0 = performance.now();
    const rs = c.program.run(cols, { chartTimeframe: "1D" });
    const res = rs.result();
    run.push(performance.now() - t0);
    if (res.error) throw new Error(`BENCH SCRIPT FAILED: ${res.error.msg} (bar ${res.error.bar})`);
  }
  // 5 studies on the same chart, each gets the same tick (the newest bar's close moves a little)
  const studies = Array.from({ length: 5 }, () => c.program.run(cols, { chartTimeframe: "1D" }));
  const last = bars - 1;
  const tick: number[] = [];
  for (let k = 0; k < rounds * 4; k++) {
    const close = cols.c[last] * (1 + ((k % 7) - 3) * 0.001);
    const bar = { o: cols.o[last], h: Math.max(cols.h[last], close), l: Math.min(cols.l[last], close), c: close, v: cols.v[last] + k };
    const t0 = performance.now();
    for (const rs of studies) {
      rs.updateLast(bar);
      rs.tick();
    }
    tick.push(performance.now() - t0);
  }
  return { lines: BENCH_SOURCE.trimEnd().split("\n").length, bars, runMs: p95(run), tickMs: p95(tick) };
}
