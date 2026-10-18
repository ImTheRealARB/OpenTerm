/**
 * GP drawings (Phase 19): trend line (a ray), horizontal line and fib retracement, anchored in (time, price) so they survive a change of
 * range or interval. Pure geometry: ChartView supplies the coordinate conversion (`Geo`), tests supply identity functions.
 */

export type DrawKind = "TREND" | "HLINE" | "FIB";
export interface DPoint {
  t: number;
  p: number;
}
export interface Drawing {
  id: string;
  kind: DrawKind;
  pts: DPoint[];
}

export const NEEDED: Record<DrawKind, number> = { TREND: 2, HLINE: 1, FIB: 2 };
export const KIND_NAME: Record<DrawKind, string> = { TREND: "TREND LINE", HLINE: "HORIZONTAL LINE", FIB: "FIB RETRACEMENT" };
export const FIB_RATIOS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1];
export const MAX_DRAWINGS = 200;

export interface Geo {
  /** Pixel x of a time, or null when the chart cannot place it. */
  toX(t: number): number | null;
  toY(p: number): number | null;
  /** Drawing width in px (rays and levels run to the right edge). */
  width: number;
}

export interface Seg {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  label?: string;
  /** Price a horizontal line or fib level stands at (for its label). */
  price?: number;
}

/** 0% is the end of the move, 100% its start (retracement back toward the start). */
export function fibLevels(p0: number, p1: number): { ratio: number; price: number }[] {
  return FIB_RATIOS.map((ratio) => ({ ratio, price: p1 - ratio * (p1 - p0) }));
}

/** Fractional bar index of a time: between bars it interpolates, past either end it extrapolates by that end's bar step. */
export function timeToLogical(t: number, times: ArrayLike<number>): number {
  const n = times.length;
  if (n === 0) return NaN;
  if (n === 1) return 0;
  if (t <= times[0]) return (t - times[0]) / (times[1] - times[0]);
  if (t >= times[n - 1]) return n - 1 + (t - times[n - 1]) / (times[n - 1] - times[n - 2]);
  let lo = 0;
  let hi = n - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (times[mid] <= t) lo = mid;
    else hi = mid;
  }
  return lo + (t - times[lo]) / (times[lo + 1] - times[lo]);
}

/**
 * The bar time that holds a calendar date (YYYY-MM-DD, UTC end of day): the last bar opened by then, if that bar's own period
 * still covers it. A date with no bar (weekend, outside the data) gives null: it is skipped, never moved to a neighbour.
 */
export function snapDay(iso: string, times: ArrayLike<number>, intervalS: number): number | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  const n = times.length;
  if (!m || n === 0) return null;
  const eod = Date.UTC(+m[1], +m[2] - 1, +m[3], 23, 59, 59) / 1000;
  if (eod < times[0]) return null;
  let lo = 0;
  let hi = n - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (times[mid] <= eod) lo = mid;
    else hi = mid - 1;
  }
  return eod < times[lo] + Math.max(intervalS, 86400) ? times[lo] : null;
}

export function segments(d: Drawing, g: Geo): Seg[] {
  if (d.pts.length < NEEDED[d.kind]) return []; // not fully anchored yet
  const px = d.pts.map((p) => ({ x: g.toX(p.t), y: g.toY(p.p) }));
  if (d.kind === "HLINE") {
    const y = px[0]?.y;
    return y == null ? [] : [{ x1: 0, y1: y, x2: g.width, y2: y, price: d.pts[0].p }];
  }
  if (px.some((p) => p.x === null || p.y === null)) return [];
  const [a, b] = px as { x: number; y: number }[];
  const [l, r] = a.x <= b.x ? [a, b] : [b, a];
  const end = Math.max(g.width, r.x);
  if (d.kind === "TREND") {
    const slope = r.x === l.x ? 0 : (r.y - l.y) / (r.x - l.x);
    return [{ x1: l.x, y1: l.y, x2: end, y2: r.x === l.x ? r.y : r.y + slope * (end - r.x) }];
  }
  const out: Seg[] = [];
  for (const lv of fibLevels(d.pts[0].p, d.pts[1].p)) {
    const y = g.toY(lv.price);
    if (y !== null) out.push({ x1: l.x, y1: y, x2: end, y2: y, label: `${(lv.ratio * 100).toFixed(1)}%`, price: lv.price });
  }
  out.push({ x1: a.x, y1: a.y, x2: b.x, y2: b.y });
  return out;
}

export function distToSegment(px: number, py: number, s: Seg): number {
  const dx = s.x2 - s.x1;
  const dy = s.y2 - s.y1;
  const len2 = dx * dx + dy * dy;
  if (len2 === 0) return Math.hypot(px - s.x1, py - s.y1);
  const t = Math.max(0, Math.min(1, ((px - s.x1) * dx + (py - s.y1) * dy) / len2));
  return Math.hypot(px - (s.x1 + t * dx), py - (s.y1 + t * dy));
}

/** Id of the drawing nearest to the point, within `tol` px; the later drawing wins a tie. */
export function hitTest(ds: Drawing[], px: number, py: number, g: Geo, tol = 6): string | null {
  let best: string | null = null;
  let bestD = tol;
  for (const d of ds) {
    for (const s of segments(d, g)) {
      const dist = distToSegment(px, py, s);
      if (dist <= bestD) {
        bestD = dist;
        best = d.id;
      }
    }
  }
  return best;
}

const finite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

/** Keeps only well-formed drawings (a bad stored entry must never break the chart). */
export function parseDrawings(raw: unknown): Drawing[] {
  if (!Array.isArray(raw)) return [];
  const out: Drawing[] = [];
  for (const d of raw) {
    if (out.length >= MAX_DRAWINGS) break;
    if (!d || typeof d !== "object") continue;
    const { id, kind, pts } = d as Record<string, unknown>;
    if (typeof id !== "string" || !id || id.length > 24 || !(kind === "TREND" || kind === "HLINE" || kind === "FIB")) continue;
    if (!Array.isArray(pts) || pts.length !== NEEDED[kind]) continue;
    if (!pts.every((p) => p && finite((p as DPoint).t) && finite((p as DPoint).p))) continue;
    out.push({ id, kind, pts: pts.map((p) => ({ t: (p as DPoint).t, p: (p as DPoint).p })) });
  }
  return out;
}

export function newId(ds: Drawing[]): string {
  const used = new Set(ds.map((d) => d.id));
  let n = 1;
  while (used.has(`d${n}`)) n++;
  return `d${n}`;
}

export function cycleSelection(ds: Drawing[], current: string | null, dir: 1 | -1): string | null {
  if (!ds.length) return null;
  const i = ds.findIndex((d) => d.id === current);
  if (i < 0) return dir > 0 ? ds[0].id : ds[ds.length - 1].id;
  return ds[(i + dir + ds.length) % ds.length].id;
}
