/**
 * Phase 14: geometry for the numeric-axis charts and the heat map that ResearchPanel draws under a table (smile, payoff, term
 * structure, COT history; IV surface, scenario grid). Pure (no window), so it is unit-tested. Nothing here invents a value:
 * a null point leaves a gap in the line, a null heat cell is drawn empty.
 */

export interface ChartSeries {
  name: string;
  points: [number, number | null][];
  dash?: boolean;
}

export interface ChartPayload {
  id: string;
  title: string;
  xlabel: string;
  ylabel: string;
  series: ChartSeries[];
  marks?: { x: number; label: string }[];
}

export interface HeatPayload {
  id: string;
  title: string;
  xlabel: string;
  ylabel: string;
  x: number[];
  y: string[];
  z: (number | null)[][];
  unit: string;
}

export interface Extent {
  xMin: number;
  xMax: number;
  yMin: number;
  yMax: number;
}

/** "Nice" tick values covering [min, max], about `count` of them (1-2-5 steps). */
export function niceTicks(min: number, max: number, count = 5): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [];
  if (max < min) [min, max] = [max, min];
  if (max === min) return [min];
  const raw = (max - min) / Math.max(1, count);
  const mag = 10 ** Math.floor(Math.log10(raw));
  const norm = raw / mag;
  const step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10) * mag;
  const out: number[] = [];
  const start = Math.ceil(min / step - 1e-9) * step;
  for (let v = start; v <= max + step * 1e-9; v += step) out.push(Math.abs(v) < step * 1e-9 ? 0 : Number(v.toPrecision(12)));
  return out;
}

/** Data extent of every drawable point, with a small margin on y so a flat line is still visible. Null when nothing is drawable. */
export function extentOf(series: ChartSeries[]): Extent | null {
  let xMin = Infinity, xMax = -Infinity, yMin = Infinity, yMax = -Infinity;
  for (const s of series) {
    for (const [x, y] of s.points) {
      if (y == null || !Number.isFinite(x) || !Number.isFinite(y)) continue;
      xMin = Math.min(xMin, x);
      xMax = Math.max(xMax, x);
      yMin = Math.min(yMin, y);
      yMax = Math.max(yMax, y);
    }
  }
  if (!Number.isFinite(xMin)) return null;
  if (xMax === xMin) {
    xMin -= 0.5;
    xMax += 0.5;
  }
  const pad = yMax === yMin ? Math.abs(yMax) * 0.05 || 1 : (yMax - yMin) * 0.06;
  return { xMin, xMax, yMin: yMin - pad, yMax: yMax + pad };
}

/** Compact tick label: no trailing zeros, thousands as K/M, small values keep their decimals. */
export function tickLabel(v: number): string {
  const a = Math.abs(v);
  if (a >= 1e9) return `${trim(v / 1e9)}B`;
  if (a >= 1e6) return `${trim(v / 1e6)}M`;
  if (a >= 1e4) return `${trim(v / 1e3)}K`;
  if (a >= 100) return trim(v, 0);
  if (a >= 1) return trim(v, 2);
  return trim(v, 4);
}

function trim(v: number, digits = 2): string {
  return String(Number(v.toFixed(digits)));
}

/** Polyline runs: consecutive drawable points; a null y starts a new run (a gap, never an interpolated value). */
export function runs(points: [number, number | null][]): [number, number][][] {
  const out: [number, number][][] = [];
  let cur: [number, number][] = [];
  for (const [x, y] of points) {
    if (y == null || !Number.isFinite(y) || !Number.isFinite(x)) {
      if (cur.length) out.push(cur);
      cur = [];
    } else cur.push([x, y]);
  }
  if (cur.length) out.push(cur);
  return out;
}

/** Min and max of a heat grid's finite cells, or null when it has none. */
export function heatRange(z: (number | null)[][]): [number, number] | null {
  let lo = Infinity, hi = -Infinity;
  for (const row of z) {
    for (const v of row) {
      if (v == null || !Number.isFinite(v)) continue;
      lo = Math.min(lo, v);
      hi = Math.max(hi, v);
    }
  }
  return Number.isFinite(lo) ? [lo, hi] : null;
}

/** Cell intensity 0..1 of `v` in [lo, hi] (0.12 floor so the lowest cell still shows). One hue: intensity is the only encoding. */
export function heatLevel(v: number, lo: number, hi: number): number {
  if (hi <= lo) return 0.5;
  return 0.12 + 0.88 * Math.min(1, Math.max(0, (v - lo) / (hi - lo)));
}

/** Heat cell text: IV-style unit "pct" prints a ratio as a percent with one decimal, "num" two decimals, "money" with K/M. */
export function heatText(v: number | null, unit: string): string {
  if (v == null || !Number.isFinite(v)) return "";
  if (unit === "pct") return (v * 100).toFixed(1);
  if (unit === "money") return tickLabel(v);
  return v.toFixed(2);
}
