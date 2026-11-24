/**
 * PAT:GEO (Phase 21): classic chart shapes found from swing pivots. Rule based, NOT a signal: the chart labels every match
 * `PATTERN RULE, NOT A SIGNAL` and names the rule that fired. Pure maths; it runs in the indicator worker like PAT:CANDLE.
 *
 * Swing pivots come from a zigzag with an ATR threshold: a swing high is confirmed once price has fallen `k` x ATR(14)
 * below the highest high since the last low (and the other way round). So a pivot is only known some bars AFTER it formed:
 * the scan never claims a shape before its last swing was confirmed.
 */
import { atr } from "./studies";

export interface Pivot {
  i: number;
  p: number;
  hi: boolean;
}

/** Zigzag pivots, oldest first, alternating high / low. Bars before ATR has warmed up only move the running extremes. */
export function zigzag(h: Float64Array, l: Float64Array, c: Float64Array, k = 2, atrN = 14): Pivot[] {
  const n = c.length;
  const a = atr(h, l, c, atrN);
  const piv: Pivot[] = [];
  let trend = 0; // 0 = no swing yet, 1 = rising leg (tracking its high), -1 = falling leg (tracking its low)
  let hiI = 0;
  let loI = 0;
  for (let i = 0; i < n; i++) {
    const th = k * a[i];
    if (trend >= 0 && h[i] >= h[hiI]) hiI = i;
    if (trend <= 0 && l[i] <= l[loI]) loI = i;
    if (!(th > 0)) continue;
    if (trend === 0) {
      if (hiI < i && h[hiI] - l[i] >= th) {
        piv.push({ i: hiI, p: h[hiI], hi: true });
        trend = -1;
        loI = i;
      } else if (loI < i && h[i] - l[loI] >= th) {
        piv.push({ i: loI, p: l[loI], hi: false });
        trend = 1;
        hiI = i;
      }
    } else if (trend === 1 && hiI < i && h[hiI] - l[i] >= th) {
      piv.push({ i: hiI, p: h[hiI], hi: true });
      trend = -1;
      loI = i;
    } else if (trend === -1 && loI < i && h[i] - l[loI] >= th) {
      piv.push({ i: loI, p: l[loI], hi: false });
      trend = 1;
      hiI = i;
    }
  }
  return piv;
}

/** Pattern codes. `dir`: +1 bullish shape, -1 bearish, 0 neither (it colours the outline only). `lines`: index pairs into pts. */
export const GEO_INFO: Record<number, { name: string; dir: number; lines: [number, number][] }> = {
  1: { name: "DOUBLE TOP", dir: -1, lines: [[0, 1], [1, 2], [1, 3]] },
  2: { name: "DOUBLE BOTTOM", dir: 1, lines: [[0, 1], [1, 2], [1, 3]] },
  3: { name: "HEAD AND SHOULDERS", dir: -1, lines: [[0, 1], [1, 2], [2, 3], [3, 4], [1, 3]] },
  4: { name: "INVERSE HEAD AND SHOULDERS", dir: 1, lines: [[0, 1], [1, 2], [2, 3], [3, 4], [1, 3]] },
  5: { name: "ASCENDING TRIANGLE", dir: 1, lines: [[0, 1], [2, 3]] },
  6: { name: "DESCENDING TRIANGLE", dir: -1, lines: [[0, 1], [2, 3]] },
  7: { name: "SYMMETRIC TRIANGLE", dir: 0, lines: [[0, 1], [2, 3]] },
  8: { name: "RISING WEDGE", dir: -1, lines: [[0, 1], [2, 3]] },
  9: { name: "FALLING WEDGE", dir: 1, lines: [[0, 1], [2, 3]] },
  10: { name: "BULL FLAG", dir: 1, lines: [[0, 1], [1, 2], [3, 4]] },
  11: { name: "BEAR FLAG", dir: -1, lines: [[0, 1], [1, 2], [3, 4]] },
};

export interface GeoPattern {
  code: number;
  pts: { i: number; p: number }[];
}

/** Each pattern travels from the worker as 13 numbers: code, then up to 6 (bar index, price) points, NaN-padded. */
export const GEO_STRIDE = 13;
export const GEO_MAX = 12;

/**
 * Finds the shapes in the pivots, newest last, never two that share a pivot, at most GEO_MAX (the most recent).
 * "Equal" levels are within 0.75 x ATR of each other at the later pivot.
 */
export function geoPatterns(h: Float64Array, l: Float64Array, c: Float64Array, k = 2): GeoPattern[] {
  const a = atr(h, l, c, 14);
  const P = zigzag(h, l, c, k);
  const out: GeoPattern[] = [];
  // Pivot span of the last match. A new match may not overlap it, unless it contains it whole: then the bigger shape
  // replaces the smaller one (the two bottoms inside a head and shoulders are not reported as a double bottom too).
  let lastStart = -1;
  let lastEnd = -1;
  // Start of the window `win` handed out last. Checks run biggest shape first and stop at the first hit, so a hit always
  // comes from the window handed out last.
  let winStart = -1;
  const pt = (q: Pivot) => ({ i: q.i, p: q.p });
  for (let j = 0; j < P.length; j++) {
    const tol = 0.75 * (Number.isFinite(a[P[j].i]) ? a[P[j].i] : 0);
    const win = (len: number) => {
      const s = j - len + 1;
      if (s < 0 || (s <= lastEnd && s > lastStart)) return null;
      winStart = s;
      return P.slice(s, j + 1);
    };
    const near = (x: number, y: number, m = 1) => Math.abs(x - y) <= tol * m;
    let hit: GeoPattern | null = null;
    // Head and shoulders (5 pivots): the middle swing beyond both shoulders, shoulders and neckline roughly level.
    const w5 = win(5);
    if (w5) {
      const [s1, n1, hd, n2, s2] = w5;
      const sign = s1.hi ? 1 : -1; // tops pattern if the shoulders are highs
      if (sign * (hd.p - s1.p) > tol && sign * (hd.p - s2.p) > tol && near(s1.p, s2.p, 1.5) && near(n1.p, n2.p, 1.5)) hit = { code: s1.hi ? 3 : 4, pts: w5.map(pt) };
      // Flag: a pole of at least 4 ATR, then a small channel against it under half the pole's height, roughly parallel.
      if (!hit) {
        const [p0, e1, x1, e2, x2] = w5; // pole start, pole end (first channel extreme), opposite, extreme, opposite
        const pole = e1.p - p0.p;
        const height = Math.abs(e1.p - x1.p);
        const up = pole > 0;
        const against = up ? e2.p <= e1.p + tol && x2.p <= x1.p + tol : e2.p >= e1.p - tol && x2.p >= x1.p - tol;
        if (Math.abs(pole) >= 4 * (tol / 0.75) && height <= Math.abs(pole) / 2 && against && near(e2.p - e1.p, x2.p - x1.p, 2)) {
          hit = { code: up ? 10 : 11, pts: [pt(p0), pt(e1), pt(e2), pt(x1), pt(x2)] };
        }
      }
    }
    // Double top / bottom (3 pivots): two swings at about the same level with a swing between.
    const w3 = !hit ? win(3) : null;
    if (w3 && near(w3[0].p, w3[2].p)) {
      const [x, m, y] = w3;
      hit = { code: x.hi ? 1 : 2, pts: [pt(x), pt(m), pt(y), { i: y.i, p: m.p }] };
    }
    // Triangles and wedges (4 pivots): two highs and two lows whose range narrows by at least 20%.
    const w4 = !hit ? win(4) : null;
    if (w4) {
      const hs = w4.filter((q) => q.hi);
      const ls = w4.filter((q) => !q.hi);
      const [h1, h2] = hs;
      const [l1, l2] = ls;
      const narrows = Math.abs(h2.p - l2.p) < 0.8 * Math.abs(h1.p - l1.p);
      const up = (x: Pivot, y: Pivot) => y.p > x.p + tol;
      const down = (x: Pivot, y: Pivot) => y.p < x.p - tol;
      let code = 0;
      if (narrows) {
        if (near(h1.p, h2.p) && up(l1, l2)) code = 5;
        else if (near(l1.p, l2.p) && down(h1, h2)) code = 6;
        else if (down(h1, h2) && up(l1, l2)) code = 7;
        else if (up(h1, h2) && up(l1, l2)) code = 8;
        else if (down(h1, h2) && down(l1, l2)) code = 9;
      }
      if (code) hit = { code, pts: [pt(h1), pt(h2), pt(l1), pt(l2)] };
    }
    if (hit) {
      if (winStart <= lastStart && out.length) out.pop(); // the new shape contains the last one: keep the bigger
      out.push(hit);
      lastStart = winStart;
      lastEnd = j;
    }
  }
  return out.slice(-GEO_MAX);
}

/** Flattens patterns for the worker message (Float64Array, like every other indicator output); `offset` shifts bar indices. */
export function geoFlat(ps: GeoPattern[], offset = 0): Float64Array {
  const f = new Float64Array(ps.length * GEO_STRIDE).fill(NaN);
  ps.forEach((g, n) => {
    f[n * GEO_STRIDE] = g.code;
    g.pts.slice(0, 6).forEach((q, m) => {
      f[n * GEO_STRIDE + 1 + m * 2] = q.i + offset;
      f[n * GEO_STRIDE + 2 + m * 2] = q.p;
    });
  });
  return f;
}

export function geoUnflat(f: Float64Array): GeoPattern[] {
  const out: GeoPattern[] = [];
  for (let n = 0; n + GEO_STRIDE <= f.length; n += GEO_STRIDE) {
    const pts: { i: number; p: number }[] = [];
    for (let m = 0; m < 6; m++) {
      const i = f[n + 1 + m * 2];
      if (Number.isFinite(i)) pts.push({ i, p: f[n + 2 + m * 2] });
    }
    out.push({ code: f[n], pts });
  }
  return out;
}
