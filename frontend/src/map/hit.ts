/**
 * Picking things on the map: which shape is under the pointer, and which are nearest the centre crosshair. Pure (no DOM).
 * All distances are in canvas pixels, so the answer is the same at every zoom.
 */
import { project, type Size, type View } from "./projection";
import type { Shape } from "./types";

/** A shape together with the id of the layer it came from. */
export interface Item {
  layer: string;
  shape: Shape;
}

const POINT_SLOP = 3; // extra pixels around a dot that still count as a hit (small dots are hard to aim at)
const LINE_SLOP = 5;
const BOX_SLOP = 5;

/** Distance from (px, py) to the SEGMENT (x0, y0)-(x1, y1), not the infinite line through it. */
export function segmentDistance(px: number, py: number, x0: number, y0: number, x1: number, y1: number): number {
  const dx = x1 - x0;
  const dy = y1 - y0;
  const len2 = dx * dx + dy * dy;
  const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, ((px - x0) * dx + (py - y0) * dy) / len2));
  return Math.hypot(px - (x0 + t * dx), py - (y0 + t * dy));
}

/** Distance from a pixel to the OUTLINE of a rectangle, from inside or outside (a big box must not swallow every click on it). */
function outlineDistance(px: number, py: number, x0: number, y0: number, x1: number, y1: number): number {
  const dx = Math.max(x0 - px, 0, px - x1);
  const dy = Math.max(y0 - py, 0, py - y1);
  if (dx > 0 || dy > 0) return Math.hypot(dx, dy);
  return Math.min(px - x0, x1 - px, py - y0, y1 - py);
}

/**
 * The shape under (px, py). Dots win over lines, lines over boxes (a box is usually drawn under what it contains);
 * inside one kind the nearest wins. Null when nothing is close enough.
 */
export function hitTest(items: Item[], view: View, size: Size, px: number, py: number): Item | null {
  let best: { item: Item; rank: number; d: number } | null = null;
  const consider = (item: Item, rank: number, d: number) => {
    if (!best || rank < best.rank || (rank === best.rank && d < best.d)) best = { item, rank, d };
  };
  for (const it of items) {
    const s = it.shape;
    if (s.kind === "pt") {
      const [x, y] = project(view, size, s.lon, s.lat);
      const d = Math.hypot(px - x, py - y);
      if (d <= s.r + POINT_SLOP) consider(it, 0, d);
    } else if (s.kind === "line") {
      let d = Infinity;
      let [ax, ay] = project(view, size, s.pts[0][0], s.pts[0][1]);
      for (let i = 1; i < s.pts.length; i++) {
        const [bx, by] = project(view, size, s.pts[i][0], s.pts[i][1]);
        d = Math.min(d, segmentDistance(px, py, ax, ay, bx, by));
        ax = bx;
        ay = by;
      }
      if (d <= LINE_SLOP) consider(it, 1, d);
    } else {
      const [x0, y0] = project(view, size, s.box[1], s.box[2]); // west, north = top-left
      const [x1, y1] = project(view, size, s.box[3], s.box[0]); // east, south = bottom-right
      const d = outlineDistance(px, py, x0, y0, x1, y1);
      if (d <= BOX_SLOP) consider(it, 2, d);
    }
  }
  return best ? (best as { item: Item }).item : null;
}

/** The on-screen shapes nearest the canvas centre first (their lat/lon anchor), at most `limit`. This is what N / P step through. */
export function rankByCentre(items: Item[], view: View, size: Size, limit: number): Item[] {
  const cx = size.w / 2;
  const cy = size.h / 2;
  const scored: { item: Item; d: number }[] = [];
  for (const it of items) {
    const [x, y] = project(view, size, it.shape.lon, it.shape.lat);
    if (x < 0 || y < 0 || x > size.w || y > size.h) continue;
    scored.push({ item: it, d: Math.hypot(x - cx, y - cy) });
  }
  scored.sort((a, b) => a.d - b.d);
  return scored.slice(0, limit).map((s) => s.item);
}
