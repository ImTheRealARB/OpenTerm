import { describe, expect, it } from "vitest";
import raw from "./worldData.json";
import { arcsInBounds, decodeArcs } from "./worldMap";

describe("decodeArcs", () => {
  it("turns [x0,y0,dx,dy,...] hundredths of a degree into lon/lat floats and a bounding box", () => {
    // start at (10.00, 20.00), then +1.00/+0.50, then -2.00/+0.25
    const [a] = decodeArcs([[1000, 2000, 100, 50, -200, 25]], 100);
    expect(Array.from(a.pts)).toEqual([10, 20, 11, 20.5, 9, 20.75].map((n) => Math.fround(n)));
    expect(a.bbox).toEqual([9, 20, 11, 20.75]);
  });

  it("cuts an arc where it crosses the date line, so no line is drawn across the whole map", () => {
    // 179.00 -> 180.00, then the data wraps to -179.00 (a delta of -359.00) and goes on to -178.00
    const out = decodeArcs([[17900, 1000, 100, 0, -35900, 0, 100, 0]], 100);
    expect(out).toHaveLength(2);
    expect(Array.from(out[0].pts)).toEqual([179, 10, 180, 10]);
    expect(Array.from(out[1].pts)).toEqual([-179, 10, -178, 10]);
  });

  it("ships a real world: thousands of arcs, all on the globe", () => {
    const coast = decodeArcs(raw.coast, raw.unit);
    const border = decodeArcs(raw.border, raw.unit);
    expect(coast.length).toBeGreaterThan(1000);
    expect(border.length).toBeGreaterThan(300);
    for (const a of [...coast, ...border]) {
      expect(a.bbox[2] - a.bbox[0]).toBeLessThan(180); // no arc spans the world: those were cut at the date line
      expect(a.bbox[0]).toBeGreaterThanOrEqual(-180.01);
      expect(a.bbox[2]).toBeLessThanOrEqual(180.01);
      expect(a.bbox[1]).toBeGreaterThanOrEqual(-90);
      expect(a.bbox[3]).toBeLessThanOrEqual(90);
      expect(a.pts.length).toBeGreaterThanOrEqual(4);
    }
  });

  it("has coast drawn around the Strait of Hormuz", () => {
    const coast = decodeArcs(raw.coast, raw.unit);
    expect(arcsInBounds(coast, { w: 55.6, s: 25.8, e: 57.0, n: 27.0 }).length).toBeGreaterThan(0);
  });
});

describe("arcsInBounds", () => {
  const arcs = decodeArcs([[0, 0, 100, 100], [5000, 5000, 100, 100]], 100); // one near (0,0)-(1,1), one near (50,50)-(51,51)
  it("keeps only arcs whose box touches the view", () => {
    expect(arcsInBounds(arcs, { w: -1, s: -1, e: 2, n: 2 })).toHaveLength(1);
    expect(arcsInBounds(arcs, { w: -10, s: -10, e: 60, n: 60 })).toHaveLength(2);
    expect(arcsInBounds(arcs, { w: 20, s: 20, e: 30, n: 30 })).toHaveLength(0);
  });
});

describe("speed (generous limits: a slow machine under load must still pass)", () => {
  it("decodes the whole outline once in well under a second, and culling a street-level view is much cheaper than the world", () => {
    const t0 = performance.now();
    const all = [...decodeArcs(raw.coast, raw.unit), ...decodeArcs(raw.border, raw.unit)];
    const decodeMs = performance.now() - t0;
    expect(decodeMs).toBeLessThan(500); // measured about 20-40 ms; this runs once per page, when the map first opens
    const t1 = performance.now();
    let kept = 0;
    for (let i = 0; i < 100; i++) kept += arcsInBounds(all, { w: 55.6, s: 25.8, e: 57, n: 27 }).length;
    const cullMs = (performance.now() - t1) / 100;
    expect(kept / 100).toBeLessThan(all.length / 10); // a strait touches a small share of all arcs
    expect(cullMs).toBeLessThan(5); // per frame; measured well under 1 ms
  });
});
