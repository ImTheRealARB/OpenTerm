import { describe, expect, it } from "vitest";
import { neighbor, pctBand, squarify, treemap, type Rect } from "./treemap";

const area = (r: Rect) => r.w * r.h;
const overlap = (a: Rect, b: Rect) => Math.max(0, Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x)) * Math.max(0, Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y));
const ratio = (r: Rect) => (r.w > 0 && r.h > 0 ? Math.max(r.w / r.h, r.h / r.w) : Infinity);
function rng(seed: number) {
  return () => {
    seed = (seed * 1664525 + 1013904223) >>> 0;
    return seed / 2 ** 32;
  };
}
const EPS = 1e-6;

function checkTiling(values: number[], box: Rect, rects: Rect[]) {
  const live = [...values.keys()].filter((i) => values[i] > 0);
  const total = live.reduce((s, i) => s + values[i], 0);
  const sum = live.reduce((s, i) => s + area(rects[i]), 0);
  expect(sum).toBeCloseTo(area(box), 4);
  for (const i of live) {
    expect(area(rects[i]) / area(box)).toBeCloseTo(values[i] / total, 9);
    expect(rects[i].x).toBeGreaterThanOrEqual(box.x - EPS);
    expect(rects[i].y).toBeGreaterThanOrEqual(box.y - EPS);
    expect(rects[i].x + rects[i].w).toBeLessThanOrEqual(box.x + box.w + EPS);
    expect(rects[i].y + rects[i].h).toBeLessThanOrEqual(box.y + box.h + EPS);
  }
}

describe("squarify", () => {
  it("tiles the box exactly, areas proportional to values, nothing outside", () => {
    const values = [6, 6, 4, 3, 2, 2, 1];
    const box = { x: 0, y: 0, w: 600, h: 400 };
    const rects = squarify(values, box);
    checkTiling(values, box, rects);
    for (let i = 0; i < rects.length; i++) for (let j = i + 1; j < rects.length; j++) expect(overlap(rects[i], rects[j])).toBeLessThan(1e-6);
    expect(Math.max(...rects.map(ratio))).toBeLessThan(3.5);
  });

  it("works in an offset, tall box", () => {
    const values = [10, 1, 5, 5, 2.5];
    const box = { x: 100, y: 50, w: 200, h: 700 };
    checkTiling(values, box, squarify(values, box));
  });

  it("a random universe of 500 values: exact tiling, no overlaps, tiles stay readable", () => {
    const r = rng(11);
    const values = Array.from({ length: 500 }, () => Math.exp(r() * 8));
    const box = { x: 0, y: 0, w: 1600, h: 900 };
    const rects = squarify(values, box);
    checkTiling(values, box, rects);
    const ratios = rects.map(ratio).sort((a, b) => a - b);
    expect(ratios[Math.floor(ratios.length / 2)]).toBeLessThan(2.5); // median aspect ratio
    expect(ratios[ratios.length - 1]).toBeLessThan(12);
    for (let k = 0; k < 400; k += 37) for (let j = k + 1; j < 500; j += 53) expect(overlap(rects[k], rects[j])).toBeLessThan(1e-6);
  });

  it("zero, negative and NaN values get no area and do not disturb the rest", () => {
    const values = [5, 0, -3, NaN, 5, Infinity];
    const box = { x: 0, y: 0, w: 100, h: 100 };
    const rects = squarify(values, box);
    for (const i of [1, 2, 3, 5]) expect(area(rects[i])).toBe(0);
    expect(area(rects[0]) + area(rects[4])).toBeCloseTo(10000, 6);
    expect(area(rects[0])).toBeCloseTo(5000, 6);
  });

  it("input order does not change a value's area", () => {
    const box = { x: 0, y: 0, w: 300, h: 200 };
    const a = squarify([1, 2, 3, 4], box);
    const b = squarify([4, 3, 2, 1], box);
    expect(area(a[0])).toBeCloseTo(area(b[3]), 6);
    expect(area(a[3])).toBeCloseTo(area(b[0]), 6);
  });

  it("empty, zero-size and all-zero input", () => {
    expect(squarify([], { x: 0, y: 0, w: 10, h: 10 })).toEqual([]);
    expect(squarify([1, 2], { x: 0, y: 0, w: 0, h: 10 }).every((r) => area(r) === 0)).toBe(true);
    expect(squarify([0, 0], { x: 0, y: 0, w: 10, h: 10 }).every((r) => area(r) === 0)).toBe(true);
  });
});

describe("two-level treemap (groups, then tiles)", () => {
  const groups = [
    { key: "Technology", items: [{ id: 0, value: 400 }, { id: 1, value: 300 }, { id: 2, value: 100 }] },
    { key: "Health Care", items: [{ id: 3, value: 150 }, { id: 4, value: 50 }] },
    { key: "Empty", items: [{ id: 5, value: 0 }] },
  ];
  const W = 800;
  const H = 500;
  const t = treemap(groups, W, H, { header: 14, pad: 1 });

  it("group rectangles tile the canvas in proportion to their total value", () => {
    expect(t.groups.reduce((s, g) => s + area(g), 0)).toBeCloseTo(W * H, 4);
    expect(area(t.groups[0]) / (W * H)).toBeCloseTo(800 / 1000, 9);
    expect(area(t.groups[2])).toBe(0);
    expect(t.groups.map((g) => g.value)).toEqual([800, 200, 0]);
  });

  it("every tile sits inside its group below the header band, sizes proportional within a group, no overlap", () => {
    const byGroup = (g: number) => t.tiles.filter((x) => x.group === g);
    for (const tile of t.tiles) {
      const g = t.groups[tile.group];
      expect(tile.x).toBeGreaterThanOrEqual(g.x - EPS);
      expect(tile.y).toBeGreaterThanOrEqual(g.y + g.header - EPS);
      expect(tile.x + tile.w).toBeLessThanOrEqual(g.x + g.w + EPS);
      expect(tile.y + tile.h).toBeLessThanOrEqual(g.y + g.h + EPS);
    }
    const [a, b, c] = byGroup(0);
    expect(area(a) / area(b)).toBeCloseTo(400 / 300, 9);
    expect(area(b) / area(c)).toBeCloseTo(3, 9);
    for (let i = 0; i < t.tiles.length; i++) for (let j = i + 1; j < t.tiles.length; j++) expect(overlap(t.tiles[i], t.tiles[j])).toBeLessThan(1e-6);
    expect(t.tiles.map((x) => x.id).sort()).toEqual([0, 1, 2, 3, 4]); // the zero-value item has no tile
    expect(t.groups[0].header).toBe(14);
  });

  it("a group too small for a header band gets none, and a canvas of zero size gives nothing", () => {
    const tiny = treemap([{ key: "A", items: [{ id: 0, value: 1 }] }, { key: "B", items: [{ id: 1, value: 1000 }] }], 400, 300, { header: 14, pad: 1 });
    expect(tiny.groups[0].header).toBe(0);
    expect(treemap(groups, 0, 100, { header: 14, pad: 1 }).tiles).toEqual([]);
  });
});

describe("tile navigation", () => {
  const grid: Rect[] = [
    { x: 0, y: 0, w: 100, h: 100 }, { x: 100, y: 0, w: 100, h: 100 },
    { x: 0, y: 100, w: 100, h: 100 }, { x: 100, y: 100, w: 100, h: 100 },
  ];
  it("moves to the nearest tile in the direction, stays put at the edge", () => {
    expect(neighbor(grid, 0, "right")).toBe(1);
    expect(neighbor(grid, 0, "down")).toBe(2);
    expect(neighbor(grid, 3, "left")).toBe(2);
    expect(neighbor(grid, 3, "up")).toBe(1);
    expect(neighbor(grid, 0, "left")).toBe(0);
    expect(neighbor(grid, 0, "up")).toBe(0);
    expect(neighbor([], 0, "up")).toBe(0);
  });
  it("prefers the tile that lines up over a nearer one that is off to the side", () => {
    const r: Rect[] = [{ x: 0, y: 0, w: 100, h: 100 }, { x: 110, y: 400, w: 20, h: 20 }, { x: 0, y: 150, w: 100, h: 100 }];
    expect(neighbor(r, 0, "down")).toBe(2);
  });
});

describe("colour bands", () => {
  it("signed bands by size of the move", () => {
    expect([0, 0.1, 0.24, 0.25, 0.9, 1, 1.9, 2, 2.9, 3, 12].map(pctBand)).toEqual([0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4]);
    expect([-0.3, -1.5, -2.5, -7].map(pctBand)).toEqual([-1, -2, -3, -4]);
    expect(pctBand(null)).toBe(0);
    expect(pctBand(undefined)).toBe(0);
    expect(pctBand(NaN)).toBe(0);
  });
});
