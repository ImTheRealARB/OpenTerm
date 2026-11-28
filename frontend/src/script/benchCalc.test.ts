import { describe, expect, it } from "vitest";
import { BENCH_SOURCE, benchScript } from "./benchCalc";
import { compile } from "./index";

// The bench numbers themselves are gated by scripts/bench.mjs (PERF CALC in a real browser); here we only check that the
// bench measures real work: the script compiles, is 40 lines, and runs over 10k bars without an error.
describe("Phase 25 bench script", () => {
  it("is 40 lines and compiles", () => {
    expect(BENCH_SOURCE.trimEnd().split("\n")).toHaveLength(40);
    const c = compile(BENCH_SOURCE);
    expect(c.ok, c.ok ? "" : c.errors.map((e) => `${e.line}:${e.col} ${e.msg}`).join(" | ")).toBe(true);
  });
  it("runs over 10k bars and ticks five studies", () => {
    const r = benchScript(compile, 10_000, 2);
    expect(r.lines).toBe(40);
    expect(r.runMs).toBeGreaterThan(0);
    expect(r.tickMs).toBeGreaterThanOrEqual(0);
  });
});
