/**
 * Rule-based pattern marks for GP (Phase 19): candlestick patterns and smart-money structure (swings, break of structure,
 * change of character, fair value gaps, order blocks). These are PATTERNS drawn from price rules, not signals or forecasts.
 * Pure functions on OHLC Float64Arrays; they run in the indicator worker and in unit tests.
 */

export interface PatternInfo {
  name: string;
  /** Short marker text on the chart. */
  short: string;
  /** 1 bullish, -1 bearish, 0 neutral. */
  dir: 1 | -1 | 0;
}

export const PATTERN_INFO: Record<number, PatternInfo> = {
  1: { name: "DOJI", short: "DJ", dir: 0 },
  2: { name: "HAMMER", short: "HM", dir: 1 },
  3: { name: "SHOOTING STAR", short: "SS", dir: -1 },
  4: { name: "BULL ENGULFING", short: "BE", dir: 1 },
  5: { name: "BEAR ENGULFING", short: "BE", dir: -1 },
  6: { name: "MORNING STAR", short: "MS", dir: 1 },
  7: { name: "EVENING STAR", short: "ES", dir: -1 },
  8: { name: "BULL HARAMI", short: "BH", dir: 1 },
  9: { name: "BEAR HARAMI", short: "BH", dir: -1 },
};

/**
 * One code per bar (0 = none), see PATTERN_INFO. Reversal patterns need a trend before them: the close of the bar before the
 * pattern is below (above) the close three bars earlier for bullish (bearish) ones. The pattern is stamped on its LAST bar.
 */
export function candlePatterns(o: Float64Array, h: Float64Array, l: Float64Array, c: Float64Array): Float64Array {
  const n = c.length;
  const out = new Float64Array(n);
  const down = (i0: number) => i0 >= 4 && c[i0 - 1] < c[i0 - 4];
  const up = (i0: number) => i0 >= 4 && c[i0 - 1] > c[i0 - 4];
  const body = (i: number) => Math.abs(c[i] - o[i]);
  const range = (i: number) => h[i] - l[i];
  const green = (i: number) => c[i] > o[i];
  const red = (i: number) => c[i] < o[i];
  const longBody = (i: number) => range(i) > 0 && body(i) >= 0.6 * range(i);
  for (let i = 0; i < n; i++) {
    let code = 0;
    if (i >= 2) {
      const a = i - 2;
      const b = i - 1;
      const bMid = (o[b] + c[b]) / 2;
      if (down(a) && red(a) && longBody(a) && body(b) <= 0.3 * body(a) && bMid <= c[a] && green(i) && c[i] > (o[a] + c[a]) / 2) code = 6;
      else if (up(a) && green(a) && longBody(a) && body(b) <= 0.3 * body(a) && bMid >= c[a] && red(i) && c[i] < (o[a] + c[a]) / 2) code = 7;
    }
    if (!code && i >= 1) {
      const p = i - 1;
      if (down(p) && red(p) && green(i) && o[i] <= c[p] && c[i] >= o[p] && body(i) > body(p)) code = 4;
      else if (up(p) && green(p) && red(i) && o[i] >= c[p] && c[i] <= o[p] && body(i) > body(p)) code = 5;
      else if (down(p) && red(p) && longBody(p) && green(i) && o[i] >= c[p] && c[i] <= o[p] && body(i) < body(p)) code = 8;
      else if (up(p) && green(p) && longBody(p) && red(i) && o[i] <= c[p] && c[i] >= o[p] && body(i) < body(p)) code = 9;
    }
    if (!code && range(i) > 0) {
      const r = range(i);
      const upper = h[i] - Math.max(o[i], c[i]);
      const lower = Math.min(o[i], c[i]) - l[i];
      const b = body(i);
      if (b >= 0.1 * r && lower >= 2 * b && upper <= 0.1 * r && down(i)) code = 2;
      else if (b >= 0.1 * r && upper >= 2 * b && lower <= 0.1 * r && up(i)) code = 3;
      else if (b <= 0.1 * r) code = 1;
    }
    out[i] = code;
  }
  return out;
}

export interface SmcZone {
  kind: "FVG" | "OB";
  dir: 1 | -1;
  /** First and last bar index of the zone (last = fill bar, or the final bar while it is still open). */
  i0: number;
  i1: number;
  top: number;
  bot: number;
  filled: boolean;
}

export interface Smc {
  /** +1 swing high, -1 swing low, stamped on the swing bar itself (known only `k` bars later). */
  swing: Float64Array;
  /** On the breaking bar: +1 / -1 break of structure (with the trend), +2 / -2 change of character (against it). */
  bos: Float64Array;
  zones: SmcZone[];
}

export function smc(o: Float64Array, h: Float64Array, l: Float64Array, c: Float64Array, k = 3): Smc {
  const n = c.length;
  const swing = new Float64Array(n);
  const bos = new Float64Array(n);
  const zones: SmcZone[] = [];
  for (let i = k; i < n - k; i++) {
    let hi = true;
    let lo = true;
    for (let j = 1; j <= k; j++) {
      if (!(h[i] > h[i - j]) || !(h[i] >= h[i + j])) hi = false;
      if (!(l[i] < l[i - j]) || !(l[i] <= l[i + j])) lo = false;
    }
    swing[i] = hi ? 1 : lo ? -1 : 0;
  }
  let lastHigh: { idx: number; val: number; broken: boolean } | null = null;
  let lastLow: { idx: number; val: number; broken: boolean } | null = null;
  let trend = 0;
  for (let i = 0; i < n; i++) {
    const s = i - k;
    if (s >= 0 && swing[s] === 1) lastHigh = { idx: s, val: h[s], broken: false };
    else if (s >= 0 && swing[s] === -1) lastLow = { idx: s, val: l[s], broken: false };
    if (lastHigh && !lastHigh.broken && c[i] > lastHigh.val) {
      bos[i] = trend === -1 ? 2 : 1;
      trend = 1;
      lastHigh.broken = true;
      const from = lastLow ? lastLow.idx : 0;
      for (let j = i - 1; j >= from; j--) {
        if (c[j] < o[j]) {
          zones.push({ kind: "OB", dir: 1, i0: j, i1: n - 1, top: h[j], bot: l[j], filled: false });
          const z = zones[zones.length - 1];
          for (let t = i + 1; t < n; t++) if (c[t] < z.bot) { z.filled = true; z.i1 = t; break; }
          break;
        }
      }
    } else if (lastLow && !lastLow.broken && c[i] < lastLow.val) {
      bos[i] = trend === 1 ? -2 : -1;
      trend = -1;
      lastLow.broken = true;
      const from = lastHigh ? lastHigh.idx : 0;
      for (let j = i - 1; j >= from; j--) {
        if (c[j] > o[j]) {
          zones.push({ kind: "OB", dir: -1, i0: j, i1: n - 1, top: h[j], bot: l[j], filled: false });
          const z = zones[zones.length - 1];
          for (let t = i + 1; t < n; t++) if (c[t] > z.top) { z.filled = true; z.i1 = t; break; }
          break;
        }
      }
    }
  }
  for (let i = 2; i < n; i++) {
    if (l[i] > h[i - 2]) {
      const z: SmcZone = { kind: "FVG", dir: 1, i0: i - 1, i1: n - 1, top: l[i], bot: h[i - 2], filled: false };
      for (let t = i + 1; t < n; t++) if (l[t] <= z.bot) { z.filled = true; z.i1 = t; break; }
      zones.push(z);
    } else if (h[i] < l[i - 2]) {
      const z: SmcZone = { kind: "FVG", dir: -1, i0: i - 1, i1: n - 1, top: l[i - 2], bot: h[i], filled: false };
      for (let t = i + 1; t < n; t++) if (h[t] >= z.top) { z.filled = true; z.i1 = t; break; }
      zones.push(z);
    }
  }
  return { swing, bos, zones };
}

/** Flattens the latest open zones for the worker reply: 6 numbers per zone [kind 1=FVG 2=OB, dir, i0, i1, top, bot]. */
export function smcZonesFlat(zones: SmcZone[], offset = 0, maxFvg = 6, maxOb = 3): Float64Array {
  const open = (kind: SmcZone["kind"], max: number) => zones.filter((z) => z.kind === kind && !z.filled).slice(-max);
  const pick = [...open("FVG", maxFvg), ...open("OB", maxOb)];
  const out = new Float64Array(pick.length * 6);
  pick.forEach((z, j) => out.set([z.kind === "FVG" ? 1 : 2, z.dir, z.i0 + offset, z.i1 + offset, z.top, z.bot], j * 6));
  return out;
}
