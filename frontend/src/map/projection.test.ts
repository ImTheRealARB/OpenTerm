import { describe, expect, it } from "vitest";
import { clampView, fitBox, minZoom, panBy, project, unproject, viewBounds, zoomAt, MAX_LAT, type View } from "./projection";

const SIZE = { w: 800, h: 500 };
const world: View = { lon: 0, lat: 0, zoom: minZoom(SIZE) };

describe("project / unproject (Web Mercator)", () => {
  it("puts the view centre in the middle of the canvas", () => {
    const v: View = { lon: 56.3, lat: 26.4, zoom: 6 };
    const [x, y] = project(v, SIZE, 56.3, 26.4);
    expect(x).toBeCloseTo(400, 6);
    expect(y).toBeCloseTo(250, 6);
  });

  it("round-trips lon/lat through the screen", () => {
    const v: View = { lon: 10, lat: 40, zoom: 4.3 };
    for (const [lon, lat] of [[-120, 35], [0, 0], [139.7, 35.7], [-70, -33], [100, 70]]) {
      const [x, y] = project(v, SIZE, lon, lat);
      const [lo, la] = unproject(v, SIZE, x, y);
      expect(lo).toBeCloseTo(lon, 6);
      expect(la).toBeCloseTo(lat, 6);
    }
  });

  it("north is up and east is right", () => {
    const v: View = { lon: 0, lat: 0, zoom: 3 };
    const [x0, y0] = project(v, SIZE, 0, 0);
    const [x1, y1] = project(v, SIZE, 10, 10);
    expect(x1).toBeGreaterThan(x0);
    expect(y1).toBeLessThan(y0);
  });

  it("doubles in size for every zoom level", () => {
    const a = project({ lon: 0, lat: 0, zoom: 3 }, SIZE, 10, 0)[0] - 400;
    const b = project({ lon: 0, lat: 0, zoom: 4 }, SIZE, 10, 0)[0] - 400;
    expect(b / a).toBeCloseTo(2, 9);
  });

  it("clamps latitudes the Mercator world cannot show instead of returning Infinity", () => {
    const [, y] = project({ lon: 0, lat: 0, zoom: 3 }, SIZE, 0, 90);
    expect(Number.isFinite(y)).toBe(true);
    expect(MAX_LAT).toBeCloseTo(85.0511, 3);
  });
});

describe("pan and zoom", () => {
  it("zoomAt keeps the point under the cursor where it was", () => {
    const v: View = { lon: 30, lat: 20, zoom: 4 };
    const before = unproject(v, SIZE, 600, 100);
    const z = zoomAt(v, SIZE, 600, 100, 1.5);
    const after = unproject(z, SIZE, 600, 100);
    expect(z.zoom).toBeCloseTo(5.5, 9);
    expect(after[0]).toBeCloseTo(before[0], 6);
    expect(after[1]).toBeCloseTo(before[1], 6);
  });

  it("panBy moves the map under the finger: dragging right shows what is to the west", () => {
    const v: View = { lon: 0, lat: 0, zoom: 5 };
    expect(panBy(v, SIZE, 100, 0).lon).toBeLessThan(0);
    expect(panBy(v, SIZE, 0, 100).lat).toBeGreaterThan(0); // dragging down shows the north
  });

  it("will not zoom out past the whole world or in past street level", () => {
    const out = zoomAt(world, SIZE, 400, 250, -5);
    expect(out.zoom).toBeCloseTo(minZoom(SIZE), 9);
    const inn = zoomAt(world, SIZE, 400, 250, 99);
    expect(inn.zoom).toBe(12);
  });

  it("keeps the edges of the canvas inside the world", () => {
    const v = clampView({ lon: 400, lat: 89, zoom: 3 }, SIZE);
    const b = viewBounds(v, SIZE);
    expect(b.e).toBeLessThanOrEqual(180 + 1e-9); // dragged past the date line: stops at the world's edge
    expect(b.n).toBeLessThanOrEqual(MAX_LAT + 1e-9);
  });

  it("at the minimum zoom the world covers the whole canvas", () => {
    const b = viewBounds(world, SIZE);
    expect(b.w).toBeLessThanOrEqual(-180 + 1e-6);
    expect(b.e).toBeGreaterThanOrEqual(180 - 1e-6);
  });
});

describe("fitBox and viewBounds", () => {
  it("fits a chokepoint box inside the canvas with padding", () => {
    const hormuz: [number, number, number, number] = [25.8, 55.6, 27.0, 57.0];
    const v = fitBox(hormuz, SIZE, 60);
    const [x0, y0] = project(v, SIZE, 55.6, 27.0);
    const [x1, y1] = project(v, SIZE, 57.0, 25.8);
    expect(x0).toBeGreaterThanOrEqual(59);
    expect(y0).toBeGreaterThanOrEqual(59);
    expect(x1).toBeLessThanOrEqual(741);
    expect(y1).toBeLessThanOrEqual(441);
    // and it is the tight fit: one of the axes touches the padding
    expect(Math.min(x0 - 60, 740 - x1, y0 - 60, 440 - y1)).toBeLessThan(1);
  });

  it("viewBounds are the lon/lat of the canvas corners", () => {
    const v: View = { lon: 10, lat: 45, zoom: 6 };
    const b = viewBounds(v, SIZE);
    const [wn, nn] = unproject(v, SIZE, 0, 0);
    const [ee, ss] = unproject(v, SIZE, SIZE.w, SIZE.h);
    expect(b.w).toBeCloseTo(wn, 9);
    expect(b.n).toBeCloseTo(nn, 9);
    expect(b.e).toBeCloseTo(ee, 9);
    expect(b.s).toBeCloseTo(ss, 9);
  });
});
