import { describe, expect, it } from "vitest";
import { compile, type BarCols, type ScriptResult } from "./index";

/**
 * OpenTerm Script conformance suite, TypeScript side (spec docs/specs/PHASE_25.md section 3).
 *
 * `backend/tests/fixtures/script_conformance.json` is ONE contract for two engines: `backend/tests/test_script_conformance.py`
 * runs it through the Python port, this file runs the same cases through the TypeScript engine. The answers were worked out by
 * hand, so when an engine disagrees, that engine has the bug (the case format is documented at the top of the Python file).
 *
 * Differences from the Python runner, all on purpose:
 * - `ts_only` cases (they use `lib.*`) RUN here and must match; Python only checks that it refuses them.
 * - The engine returns Float64Array with NaN for na and Uint8Array for conditions; they are turned into plain arrays with
 *   `null` before comparing, so the JSON stays the single source of truth.
 *
 * vitest has no @types/node, so Node's `fs` is reached through `process.getBuiltinModule` (same trick as examples.test.ts).
 */
interface Fs {
  readFileSync(p: URL, enc: string): string;
}
const nodeFs = (globalThis as unknown as { process: { getBuiltinModule(id: string): Fs } }).process.getBuiltinModule("node:fs");
const file = new URL("../../../backend/tests/fixtures/script_conformance.json", import.meta.url);

interface Case {
  name: string;
  source: string;
  bars: BarCols;
  inputs?: Record<string, unknown>;
  requests?: Record<string, BarCols>;
  chart_timeframe?: string;
  ts_only?: boolean;
  expect: {
    plots?: Record<string, (number | null)[]>;
    outputs?: Record<string, unknown>[];
    drawings?: Record<string, unknown[]>;
    alerts?: { bar: number; message: string }[];
    conditions?: Record<string, number[]>;
    compile_error?: string;
    runtime_error?: string;
    error_bar?: number;
  };
}
const CASES = JSON.parse(nodeFs.readFileSync(file, "utf8")) as Case[];

/** Same tolerance as the Python runner: 1e-12 absolute or 1e-9 relative. null = na. */
function sameNumber(a: number | null, b: number | null): boolean {
  if (a === null || b === null) return a === null && b === null;
  const diff = Math.abs(a - b);
  return diff <= 1e-12 || diff <= 1e-9 * Math.max(Math.abs(a), Math.abs(b));
}

/** Engine value to JSON shape: typed arrays become plain arrays, NaN becomes null (na). */
function plain(v: unknown): unknown {
  if (typeof v === "number") return Number.isNaN(v) ? null : v;
  if (v instanceof Float64Array || v instanceof Uint8Array) return Array.from(v, (x) => (Number.isNaN(x) ? null : x));
  if (Array.isArray(v)) return v.map(plain);
  if (v && typeof v === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, x] of Object.entries(v)) out[k] = plain(x);
    return out;
  }
  return v;
}

/** null when `actual` fits `expected` (objects: only the listed keys), else a sentence saying where it does not. */
function matches(expected: unknown, actual: unknown, path = ""): string | null {
  if (expected !== null && typeof expected === "object" && !Array.isArray(expected)) {
    if (actual === null || typeof actual !== "object" || Array.isArray(actual)) return `${path}: expected an object, got ${JSON.stringify(actual)}`;
    const a = actual as Record<string, unknown>;
    for (const [k, v] of Object.entries(expected)) {
      if (!(k in a)) return `${path}.${k}: missing in ${Object.keys(a).sort().join(",")}`;
      const bad = matches(v, a[k], `${path}.${k}`);
      if (bad) return bad;
    }
    return null;
  }
  if (Array.isArray(expected)) {
    if (!Array.isArray(actual) || actual.length !== expected.length) return `${path}: expected ${expected.length} items, got ${JSON.stringify(actual)}`;
    for (let i = 0; i < expected.length; i++) {
      const bad = matches(expected[i], actual[i], `${path}[${i}]`);
      if (bad) return bad;
    }
    return null;
  }
  if (typeof expected === "string" || typeof expected === "boolean") {
    return expected === actual ? null : `${path}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`;
  }
  if (expected === null || typeof expected === "number") {
    if (actual !== null && typeof actual !== "number") return `${path}: expected a number or null, got ${JSON.stringify(actual)}`;
    return sameNumber(expected, actual as number | null) ? null : `${path}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`;
  }
  return `${path}: cannot compare ${JSON.stringify(expected)}`;
}

function check(c: Case, raw: ScriptResult): void {
  const exp = c.expect;
  const r = plain(raw) as {
    plots: Record<string, unknown>[];
    drawings: Record<string, unknown[]>;
    alerts: unknown[];
    conditions: { title: string; values: unknown[] }[];
    error?: { msg: string; bar: number };
  };
  if (exp.runtime_error !== undefined) {
    expect(r.error, "expected a runtime error, the run finished").toBeDefined();
    expect(r.error!.msg).toContain(exp.runtime_error);
    if (exp.error_bar !== undefined) expect(r.error!.bar).toBe(exp.error_bar);
  } else {
    expect(r.error).toBeUndefined();
  }
  for (const [title, values] of Object.entries(exp.plots ?? {})) {
    const found = r.plots.find((p) => p.kind === "plot" && p.title === title);
    expect(found, `no plot titled ${title}`).toBeDefined();
    expect(matches(values, found!.values, title)).toBeNull();
  }
  (exp.outputs ?? []).forEach((wantRaw, j) => {
    expect(j < r.plots.length, `no output ${j}`).toBe(true);
    const entry = r.plots[j];
    const { absent = [], ...want } = wantRaw as { absent?: string[] } & Record<string, unknown>;
    for (const key of absent) expect(key in entry, `output ${j} should not have ${key}`).toBe(false);
    expect(matches(want, entry, `outputs[${j}]`)).toBeNull();
  });
  for (const [kind, want] of Object.entries(exp.drawings ?? {})) {
    expect(matches(want, r.drawings[kind], kind)).toBeNull();
  }
  if (exp.alerts) expect(r.alerts).toEqual(exp.alerts);
  for (const [title, values] of Object.entries(exp.conditions ?? {})) {
    const found = r.conditions.find((x) => x.title === title);
    expect(found, `no condition titled ${title}`).toBeDefined();
    expect(found!.values).toEqual(values);
  }
}

describe("conformance (shared with the Python port)", () => {
  it("the contract file is loaded", () => {
    expect(CASES.length).toBeGreaterThanOrEqual(45);
  });

  for (const c of CASES) {
    it(c.name, () => {
      const compiled = compile(c.source);
      if (c.expect.compile_error !== undefined) {
        expect(compiled.ok).toBe(false);
        if (compiled.ok) return;
        const msgs = compiled.errors.map((e) => e.msg);
        expect(msgs.some((m) => m.includes(c.expect.compile_error!)), msgs.join(" | ")).toBe(true);
        for (const e of compiled.errors) {
          expect(e.line).toBeGreaterThanOrEqual(1);
          expect(e.col).toBeGreaterThanOrEqual(1);
        }
        return;
      }
      expect(compiled.ok, compiled.ok ? "" : compiled.errors.map((e) => `${e.line}:${e.col} ${e.msg}`).join(" | ")).toBe(true);
      if (!compiled.ok) return;
      const run = compiled.program.run(c.bars, { inputs: c.inputs, requests: c.requests, chartTimeframe: c.chart_timeframe });
      check(c, run.result());
    });
  }
});
