import { describe, expect, it } from "vitest";
import { hitTest, rankByCentre, segmentDistance, type Item } from "./hit";
import { project, type View } from "./projection";
import type { Shape } from "./types";

const SIZE = { w: 800, h: 500 };
const V: View = { lon: 0, lat: 0, zoom: 5 };

const pt = (id: string, lon: number, lat: number, r = 4): Shape => ({ kind: "pt", id, label: id, tone: "acc", detail: [], lon, lat, r });
const item = (layer: string, shape: Shape): Item => ({ layer, shape });

describe("segmentDistance", () => {
  it("measures to the segment, not the infinite line", () => {
    expect(segmentDistance(5, 5, 0, 0, 10, 0)).toBe(5);
    expect(segmentDistance(15, 0, 0, 0, 10, 0)).toBe(5); // beyond the end: distance to the end point
    expect(segmentDistance(3, 4, 0, 0, 0, 0)).toBe(5); // a zero-length segment is a point
  });
});

describe("hitTest", () => {
  it("picks the dot under the pointer, within its radius plus a small slop", () => {
    const items = [item("q", pt("a", 0, 0)), item("q", pt("b", 1, 1))];
    const [ax, ay] = project(V, SIZE, 0, 0);
    expect(hitTest(items, V, SIZE, ax + 3, ay)?.shape.id).toBe("a");
    expect(hitTest(items, V, SIZE, ax + 40, ay)).toBeNull();
  });

  it("prefers the nearer of two overlapping dots", () => {
    const items = [item("q", pt("far", -0.02, 0, 8)), item("q", pt("near", 0, 0, 8))];
    const [x, y] = project(V, SIZE, 0, 0);
    expect(hitTest(items, V, SIZE, x + 1, y)?.shape.id).toBe("near");
  });

  it("hits a line near its path and a box on its border", () => {
    const line: Shape = { kind: "line", id: "l", label: "l", tone: "warn", detail: [], pts: [[0, 0], [2, 0]], lat: 0, lon: 2 };
    const box: Shape = { kind: "box", id: "b", label: "b", tone: "dim", detail: [], box: [5, 5, 6, 6], lat: 5.5, lon: 5.5 };
    const items = [item("e", line), item("c", box)];
    const [mx, my] = project(V, SIZE, 1, 0);
    expect(hitTest(items, V, SIZE, mx, my + 2)?.shape.id).toBe("l");
    const [bx, by] = project(V, SIZE, 5, 5.5); // west edge
    expect(hitTest(items, V, SIZE, bx + 1, by)?.shape.id).toBe("b");
    const [cx, cy] = project(V, SIZE, 5.5, 5.5); // inside, far from the border: not a hit
    expect(hitTest(items, V, SIZE, cx, cy)).toBeNull();
  });

  it("dots win over boxes drawn under them", () => {
    const box: Shape = { kind: "box", id: "b", label: "b", tone: "dim", detail: [], box: [-1, -1, 1, 1], lat: 0, lon: 0 };
    const items = [item("c", box), item("q", pt("dot", -1, 0))];
    const [x, y] = project(V, SIZE, -1, 0);
    expect(hitTest(items, V, SIZE, x, y)?.shape.id).toBe("dot");
  });
});

describe("rankByCentre", () => {
  it("lists on-screen shapes nearest the canvas centre first and skips off-screen ones", () => {
    const items = [item("q", pt("far", 5, 0)), item("q", pt("near", 0.5, 0)), item("q", pt("gone", 120, 0)), item("q", pt("mid", -2, 0))];
    expect(rankByCentre(items, V, SIZE, 10).map((i) => i.shape.id)).toEqual(["near", "mid", "far"]);
    expect(rankByCentre(items, V, SIZE, 2)).toHaveLength(2);
  });
});
