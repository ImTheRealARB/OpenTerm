import { describe, expect, it } from "vitest";
import { compile } from "./index";

/**
 * The 20 starter scripts (backend/openterm/script/examples/*.ots, served by GET /api/scripts/examples) must all compile and run
 * over 300 bars with no error. They are the first thing a new user opens, so a script that does not run is a bug in the
 * script or in the engine, never something to hide.
 *
 * vitest blanks CSS imports and the project has no @types/node, so Node's `fs` is reached through `process.getBuiltinModule`
 * (same trick as settings/themes.test.ts).
 */
interface Fs {
  readdirSync(p: URL): string[];
  readFileSync(p: URL, enc: string): string;
}
const nodeFs = (globalThis as unknown as { process: { getBuiltinModule(id: string): Fs } }).process.getBuiltinModule("node:fs");
const dir = new URL("../../../backend/openterm/script/examples/", import.meta.url);
const files = nodeFs.readdirSync(dir).filter((f) => f.endsWith(".ots")).sort();

/** What the checks below read from the engine's answers (structural: the engine's own types are richer). */
interface CompileLike {
  ok: boolean;
  errors?: { msg: string; line: number; col: number }[];
  program?: {
    meta: { title: string; requests: { symbol: string; timeframe: string }[]; conditions: unknown[]; usesLib: boolean };
    run(bars: Bars, opts?: { inputs?: Record<string, unknown>; requests?: Record<string, Bars>; chartTimeframe?: string }): {
      result(): {
        plots: unknown[];
        drawings: Record<string, unknown[]>;
        alerts: unknown[];
        conditions: unknown[];
        error?: { msg: string; line: number; col: number; bar: number };
      };
    };
  };
}
type Bars = { o: Float64Array; h: Float64Array; l: Float64Array; c: Float64Array; v: Float64Array; t: Float64Array };

/** A repeatable random walk of daily bars (a small seeded generator, so a failure always reproduces). */
function syntheticBars(n: number, seed: number): Bars {
  const b: Bars = { o: new Float64Array(n), h: new Float64Array(n), l: new Float64Array(n), c: new Float64Array(n), v: new Float64Array(n), t: new Float64Array(n) };
  let s = seed;
  const rnd = () => {
    s = (s * 1664525 + 1013904223) % 4294967296;
    return s / 4294967296;
  };
  let price = 100;
  for (let i = 0; i < n; i++) {
    const open = price;
    price = Math.max(1, price * (1 + (rnd() - 0.48) * 0.04));
    b.o[i] = open;
    b.c[i] = price;
    b.h[i] = Math.max(open, price) * (1 + rnd() * 0.01);
    b.l[i] = Math.min(open, price) * (1 - rnd() * 0.01);
    b.v[i] = 1_000_000 * (0.5 + rnd()) * (rnd() < 0.05 ? 4 : 1); // a few volume spikes
    b.t[i] = 1_700_000_000 + i * 86400;
  }
  return b;
}

describe("the starter examples", () => {
  it("there are 20 of them, each starting with one // comment sentence and then indicator(...)", () => {
    expect(files).toHaveLength(20);
    for (const f of files) {
      const src = nodeFs.readFileSync(new URL(f, dir), "utf8");
      const lines = src.split("\n");
      expect(lines[0].startsWith("// "), f).toBe(true);
      expect(lines[0].trim().endsWith("."), `${f}: the header comment is one sentence ending in a full stop`).toBe(true);
      expect(lines[1].startsWith("indicator("), f).toBe(true);
      expect(src.length, f).toBeLessThanOrEqual(20_000);
    }
  });

  it.each(files)("%s compiles and runs over 300 bars without an error", (f) => {
    const src = nodeFs.readFileSync(new URL(f, dir), "utf8");
    const c = compile(src) as unknown as CompileLike;
    expect(c.ok, `${f}: ${JSON.stringify(c.errors)}`).toBe(true);
    const program = c.program!;
    // Other symbols and timeframes (request) are fetched by the chart before the run; here they are synthetic bars.
    const requests: Record<string, Bars> = {};
    program.meta.requests.forEach((r, i) => {
      requests[`${r.symbol}|${r.timeframe}`] = syntheticBars(300, 1000 + i);
    });
    const out = program.run(syntheticBars(300, 42), { requests, chartTimeframe: "1D" }).result();
    expect(out.error, `${f}: ${JSON.stringify(out.error)}`).toBeUndefined();
    // A script must draw or declare something: an empty result means the script is a no-op.
    const drawn = out.plots.length + out.alerts.length + out.conditions.length + Object.values(out.drawings).reduce((a, d) => a + d.length, 0);
    expect(drawn, `${f}: nothing came out`).toBeGreaterThan(0);
  });

  it("the alert example records a message and the breakout example declares two conditions", () => {
    const run = (f: string) => {
      const c = compile(nodeFs.readFileSync(new URL(f, dir), "utf8")) as unknown as CompileLike;
      return c.program!.run(syntheticBars(300, 42), { chartTimeframe: "1D" }).result();
    };
    expect(run("breakout_conditions.ots").conditions).toHaveLength(2);
    expect(run("sma_cross.ots").conditions).toHaveLength(2);
    // RSI crosses back above 30 at least once on 300 random bars, so alert() recorded a message.
    expect(run("rsi_alert.ots").alerts.length).toBeGreaterThan(0);
  });
});
