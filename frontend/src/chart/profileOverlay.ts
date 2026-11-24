/**
 * Phase 23: the GP studies that are drawn on the overlay canvas rather than as chart series, because they are not one value
 * per bar: volume profiles (horizontal histograms) and the ANCHORED VWAP (it starts at a bar the user picks).
 *
 *   VP       one profile of the bars on screen, against the right edge of the plot (recomputed on pan / zoom: cheap)
 *   VP:S     one profile per session (overnight gap > 4 h), drawn inside the session's own columns
 *   VP:A     anchored / fixed range: from the LAST vertical-line drawing to the last bar, or between the last TWO
 *            vertical lines when there are two or more (draw them with the VLINE tool)
 *   AVWAP:A  anchored VWAP with 1, 2 and 3 standard deviation bands, from the last vertical-line drawing
 *
 * Bars carry no volume-at-price, so every profile is an estimate from the chart's own bars, and says so on the chart:
 * "VP ESTIMATED FROM 1D BARS". The maths lives in `volumeProfile.ts` and `avwap.ts` (unit tested); this file only paints.
 */
import { avwap } from "./avwap";
import type { BarData, ThemeColors } from "./chartBase";
import type { Drawing, Geo } from "./drawings";
import { periods, volumeProfile, type Profile } from "./volumeProfile";

export const OVERLAY_STUDIES = ["VP", "VP:S", "VP:A", "AVWAP:A"] as const;
export type OverlayStudy = (typeof OVERLAY_STUDIES)[number];

/** Session profiles depend only on the bars: computed once per bar array (the chart replaces the array on every load). */
const sessionCache = new WeakMap<Float64Array, { range: [number, number]; p: Profile | null }[]>();

function sessionProfiles(bars: BarData) {
  let hit = sessionCache.get(bars.t);
  if (!hit) {
    hit = periods(bars.t, "SESSION").map((range) => ({ range, p: volumeProfile(bars.h, bars.l, bars.v, range[0], range[1], 24) }));
    sessionCache.set(bars.t, hit);
  }
  return hit;
}

/** First bar index at or after time `t` (bars are sorted by time). */
function indexAt(times: Float64Array, t: number): number {
  let lo = 0;
  let hi = times.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (times[mid] < t) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/**
 * Paints one profile as bars growing from `x0` towards `dir` (1 = right, -1 = left), at most `maxW` px long.
 * Value-area rows are drawn in the accent colour, the rest dim; the POC row gets a full-width line in the warning colour.
 */
function paintProfile(ctx: CanvasRenderingContext2D, p: Profile, g: Geo, c: ThemeColors, x0: number, dir: 1 | -1, maxW: number) {
  let peak = 0;
  for (let r = 0; r < p.vol.length; r++) if (p.vol[r] > peak) peak = p.vol[r];
  if (!(peak > 0)) return;
  ctx.globalAlpha = 0.35; // faint so the candles stay readable under the histogram
  for (let r = 0; r < p.vol.length; r++) {
    const yTop = g.toY(p.lo + (r + 1) * p.step);
    const yBot = g.toY(p.lo + r * p.step);
    if (yTop === null || yBot === null) continue;
    const w = (p.vol[r] / peak) * maxW;
    ctx.fillStyle = r >= p.vaLo && r <= p.vaHi ? c.acc : c.dim;
    ctx.fillRect(dir === 1 ? x0 : x0 - w, yTop, w, Math.max(1, yBot - yTop - 1));
  }
  ctx.globalAlpha = 1;
  const yPoc = g.toY(p.lo + (p.poc + 0.5) * p.step);
  if (yPoc !== null) {
    ctx.strokeStyle = c.warn;
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.moveTo(dir === 1 ? x0 : x0 - maxW, yPoc);
    ctx.lineTo(dir === 1 ? x0 + maxW : x0, yPoc);
    ctx.stroke();
  }
}

/** The anchored VWAP line and its bands, as polylines from the anchor bar to the last bar. */
function paintAvwap(ctx: CanvasRenderingContext2D, bars: BarData, from: number, to: number, g: Geo, c: ThemeColors) {
  const sub = (a: Float64Array) => a.subarray(from, to);
  // The slice already starts at the anchor bar, so "ANCHOR" at its first time sums from there and never restarts.
  const b = avwap(sub(bars.t), sub(bars.h), sub(bars.l), sub(bars.c), sub(bars.v), "ANCHOR", bars.t[from]);
  const lines: [Float64Array, string, number[]][] = [
    [b.mid, c.warn, []], [b.up1, c.dim, [4, 3]], [b.lo1, c.dim, [4, 3]], [b.up2, c.dim, [2, 4]], [b.lo2, c.dim, [2, 4]], [b.up3, c.dim, [1, 5]], [b.lo3, c.dim, [1, 5]],
  ];
  for (const [vals, col, dash] of lines) {
    ctx.strokeStyle = col;
    ctx.setLineDash(dash);
    ctx.beginPath();
    let started = false;
    for (let i = 0; i < vals.length; i++) {
      const x = g.toX(bars.t[from + i]);
      const y = Number.isFinite(vals[i]) ? g.toY(vals[i]) : null;
      if (x === null || y === null) {
        started = false;
        continue;
      }
      if (started) ctx.lineTo(x, y);
      else ctx.moveTo(x, y);
      started = true;
    }
    ctx.stroke();
  }
  ctx.setLineDash([]);
}

export interface OverlayInput {
  ctx: CanvasRenderingContext2D;
  bars: BarData;
  geo: Geo;
  colors: ThemeColors;
  studies: OverlayStudy[];
  drawings: Drawing[];
  /** Bar indexes on screen [from, to). */
  visible: [number, number];
}

/** Paints the overlay studies; returns how many primitives were drawn (for the `chart.profiles` gauge used by tests). */
export function paintOverlayStudies({ ctx, bars, geo, colors: c, studies, drawings, visible }: OverlayInput): number {
  if (!studies.length || !bars.t.length) return 0;
  let n = 0;
  const notes: string[] = [];
  ctx.save();
  ctx.beginPath();
  ctx.rect(0, 0, geo.width, geo.height ?? 10_000);
  ctx.clip();
  ctx.lineWidth = 1;
  ctx.font = `${c.fs}px ${c.font}`;
  if (studies.includes("VP")) {
    const p = volumeProfile(bars.h, bars.l, bars.v, Math.max(0, visible[0]), Math.min(bars.t.length, visible[1]));
    if (p) {
      paintProfile(ctx, p, geo, c, geo.width, -1, geo.width * 0.25);
      n++;
    }
  }
  if (studies.includes("VP:S")) {
    for (const { range, p } of sessionProfiles(bars)) {
      if (!p || range[1] <= visible[0] || range[0] >= visible[1]) continue; // off screen
      const x0 = geo.toX(bars.t[range[0]]);
      const x1 = geo.toX(bars.t[range[1] - 1]);
      if (x0 === null || x1 === null) continue;
      paintProfile(ctx, p, geo, c, x0, 1, Math.max(4, x1 - x0));
      n++;
    }
  }
  // Anchors: the vertical-line drawings, oldest first (the drawings list keeps creation order).
  const vlines = drawings.filter((d) => d.kind === "VLINE" && !d.hidden && d.pts.length).map((d) => d.pts[0].t);
  const wantsAnchor = studies.includes("VP:A") || studies.includes("AVWAP:A");
  if (wantsAnchor && !vlines.length) notes.push("VP:A / AVWAP:A: DRAW A VERTICAL LINE (VLINE) TO ANCHOR");
  if (wantsAnchor && vlines.length) {
    const last = vlines[vlines.length - 1];
    if (studies.includes("VP:A")) {
      // Two or more lines: a fixed range between the last two. One line: from it to the last bar.
      const a = vlines.length >= 2 ? Math.min(last, vlines[vlines.length - 2]) : last;
      const b = vlines.length >= 2 ? Math.max(last, vlines[vlines.length - 2]) : Infinity;
      const from = indexAt(bars.t, a);
      const to = b === Infinity ? bars.t.length : indexAt(bars.t, b + 1);
      const p = volumeProfile(bars.h, bars.l, bars.v, from, to);
      const x0 = from < bars.t.length ? geo.toX(bars.t[from]) : null;
      const x1 = to > from ? geo.toX(bars.t[to - 1]) : null;
      if (p && x0 !== null && x1 !== null) {
        paintProfile(ctx, p, geo, c, x0, 1, Math.max(8, x1 - x0));
        n++;
      }
    }
    if (studies.includes("AVWAP:A")) {
      const from = indexAt(bars.t, last);
      if (from < bars.t.length) {
        paintAvwap(ctx, bars, from, bars.t.length, geo, c);
        n++;
      }
    }
  }
  if (studies.some((s) => s.startsWith("VP"))) notes.unshift(`VP ESTIMATED FROM ${bars.interval.toUpperCase()} BARS (VOLUME SPREAD OVER EACH BAR'S RANGE)`);
  ctx.fillStyle = c.dim;
  notes.forEach((t, i) => ctx.fillText(t, 4, (i + 1) * (c.fs + 3)));
  ctx.restore();
  return n;
}
