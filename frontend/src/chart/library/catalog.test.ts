import { describe, expect, it } from "vitest";
import { CATALOG, findIndicator, runIndicator } from "./catalog";
import { synth } from "./synth";
import type { Cols } from "./types";

describe("indicator catalog", () => {
  it("has about 100 unique, well-formed entries", () => {
    expect(CATALOG.length).toBeGreaterThanOrEqual(100);
    expect(new Set(CATALOG.map((d) => d.id)).size).toBe(CATALOG.length);
    for (const d of CATALOG) {
      expect(d.id).toMatch(/^[A-Z0-9_]+$/);
      expect(d.plain.length).toBeGreaterThan(15);
      expect(d.outputs.length).toBeGreaterThan(0);
      for (const p of d.params) expect(p.min <= p.default && p.default <= p.max).toBe(true);
    }
  });

  const cols = synth();
  for (const d of CATALOG) {
    it(`${d.id} runs, right length, finite after warm-up`, () => {
      const out = runIndicator(d.id, cols)!;
      expect(out.length).toBe(d.outputs.length);
      for (const a of out) {
        expect(a.length).toBe(cols.c.length);
        let finite = 0;
        for (let i = 0; i < a.length; i++) if (Number.isFinite(a[i])) finite++;
        // the tail of every output must be finite (spans/chikou of Ichimoku and pivots are the only shifted ones)
        const tail = Array.from(a.subarray(a.length - 5));
        if (!["ICHIMOKU"].includes(d.id)) expect(tail.every(Number.isFinite), `${d.id} tail ${tail}`).toBe(true);
        else expect(finite).toBeGreaterThan(100);
        expect(Array.from(a).some((x) => x === Infinity || x === -Infinity)).toBe(false);
      }
    });
  }

  it("survives tiny inputs", () => {
    const tiny: Cols = { o: Float64Array.of(1, 2), h: Float64Array.of(2, 3), l: Float64Array.of(0.5, 1), c: Float64Array.of(1.5, 2.5), v: Float64Array.of(10, 20) };
    for (const d of CATALOG) expect(() => d.fn(tiny, d.params.map((p) => p.default))).not.toThrow();
  });

  it("lookup is case insensitive and params are clamped", () => {
    expect(findIndicator("rsi")?.id).toBe("RSI");
    const a = runIndicator("SMA", cols, [100000])!;
    expect(a[0].length).toBe(cols.c.length);
  });
});
