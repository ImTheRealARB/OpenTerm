// PAT:GEO: zigzag pivots and two shapes built by hand. Bars are 1-wide (high = close + 0.5, low = close - 0.5), so ATR14
// settles near 1 plus the step size, and a 2 x ATR swing is easy to place.
import { describe, expect, it } from "vitest";
import { geoFlat, geoPatterns, geoUnflat, zigzag } from "./geoPatterns";

/** Bars that walk in straight lines between the given closes, `steps` bars per leg. */
function walk(points: number[], steps = 10) {
  const c: number[] = [];
  for (let k = 0; k + 1 < points.length; k++) for (let s = 0; s < steps; s++) c.push(points[k] + ((points[k + 1] - points[k]) * s) / steps);
  c.push(points[points.length - 1]);
  const C = Float64Array.from(c);
  return { h: C.map((x) => x + 0.5), l: C.map((x) => x - 0.5), c: C };
}

describe("PAT:GEO", () => {
  it("zigzag alternates highs and lows at the turning points", () => {
    const b = walk([100, 130, 110, 140, 120, 150]);
    const piv = zigzag(b.h, b.l, b.c);
    expect(piv.length).toBeGreaterThanOrEqual(3);
    for (let i = 1; i < piv.length; i++) expect(piv[i].hi).not.toBe(piv[i - 1].hi);
    expect(piv.find((q) => q.hi)!.p).toBe(130.5); // first swing high: the 130 close + 0.5
  });
  it("finds a double top and a head and shoulders", () => {
    const dt = walk([100, 140, 115, 140.4, 105]);
    expect(geoPatterns(dt.h, dt.l, dt.c).map((g) => g.code)).toContain(1);
    const hs = walk([100, 130, 112, 150, 112.5, 130.3, 95]);
    expect(geoPatterns(hs.h, hs.l, hs.c).map((g) => g.code)).toContain(3);
  });
  it("travels through the worker format and back with shifted bar indices", () => {
    const back = geoUnflat(geoFlat([{ code: 2, pts: [{ i: 1, p: 9 }, { i: 4, p: 12 }, { i: 7, p: 9.1 }] }], 100));
    expect(back).toEqual([{ code: 2, pts: [{ i: 101, p: 9 }, { i: 104, p: 12 }, { i: 107, p: 9.1 }] }]);
  });
});
