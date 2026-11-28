/**
 * Helpers shared by the script engine tests (not a test itself).
 */
import { compile, type BarCols, type RunOpts, type ScriptError, type ScriptResult } from "./index";

/** Daily bars from a list of closes: open = close, high = close + 1, low = close - 1, volume 100. */
export function barsFromCloses(c: number[], start = 1_700_006_400): BarCols {
  return {
    o: c.slice(),
    h: c.map((x) => x + 1),
    l: c.map((x) => x - 1),
    c: c.slice(),
    v: c.map(() => 100),
    t: c.map((_, i) => start + i * 86400),
  };
}

/** A deterministic random walk (so tests are repeatable). */
export function walk(n: number, seed = 7): BarCols {
  let s = seed;
  const rnd = () => {
    s = (s * 1664525 + 1013904223) % 4294967296;
    return s / 4294967296;
  };
  const o: number[] = [];
  const h: number[] = [];
  const l: number[] = [];
  const c: number[] = [];
  const v: number[] = [];
  const t: number[] = [];
  let px = 100;
  for (let i = 0; i < n; i++) {
    const open = px;
    px = Math.max(5, px + (rnd() - 0.5) * 4);
    const hi = Math.max(open, px) + rnd() * 2;
    const lo = Math.min(open, px) - rnd() * 2;
    o.push(open);
    h.push(hi);
    l.push(lo);
    c.push(px);
    v.push(1000 + Math.floor(rnd() * 500));
    t.push(1_700_006_400 + i * 86400);
  }
  return { o, h, l, c, v, t };
}

/** Compile, expecting success; run; return the result. */
export function runScript(src: string, bars: BarCols, opts?: RunOpts): ScriptResult {
  const r = compile(src);
  if (!r.ok) throw new Error("compile failed: " + r.errors.map((e) => `${e.line}:${e.col} ${e.msg}`).join("; "));
  return r.program.run(bars, opts).result();
}

export function compileErrors(src: string): ScriptError[] {
  const r = compile(src);
  if (r.ok) throw new Error("expected a compile error");
  return r.errors;
}

/** The values of the plot with this title, as a plain array (NaN stays NaN). */
export function plot(res: ScriptResult, title: string): number[] {
  const p = res.plots.find((x) => x.title === title);
  if (!p || !p.values) throw new Error(`no plot "${title}" (have: ${res.plots.map((x) => x.title).join(", ")})`);
  return Array.from(p.values);
}

/** Close to within an absolute / relative tolerance; NaN equals NaN. */
export function near(a: number, b: number, tol = 1e-9): boolean {
  if (a !== a || b !== b) return a !== a && b !== b;
  return Math.abs(a - b) <= Math.max(tol, tol * Math.abs(b));
}

export function expectClose(got: number[], want: number[], tol = 1e-9): void {
  if (got.length !== want.length) throw new Error(`length ${got.length} != ${want.length}`);
  for (let i = 0; i < want.length; i++) {
    if (!near(got[i], want[i], tol)) throw new Error(`index ${i}: got ${got[i]}, want ${want[i]}\n got  = ${got.join(", ")}\n want = ${want.join(", ")}`);
  }
}
