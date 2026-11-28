/**
 * Turn bars into longer bars (spec 1.5, `request` on the same symbol): 5 minute bars into 1 hour bars, daily into weekly.
 * Pure. Bars are columns (`Cols`) with `t` = bar open time in epoch SECONDS (UTC).
 *
 * Buckets:
 *   1m 5m 15m 30m 1h 2h 4h   aligned to the epoch (UTC), e.g. 1h = whole hours
 *   1D                        UTC calendar day
 *   1W                        weeks starting on MONDAY (UTC)
 *   1M                        UTC calendar month
 * A resampled bar has: open = first open, high = highest high, low = lowest low, close = last close, volume = sum,
 * t = the bucket's start.
 */
import { TIMEFRAMES } from "./names";

export interface TCols {
  o: Float64Array;
  h: Float64Array;
  l: Float64Array;
  c: Float64Array;
  v: Float64Array;
  t: Float64Array;
}

const SEC: Record<string, number> = { "1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400, "1D": 86400, "1W": 604800, "1M": 2592000 };

/** "60" / "D" / "1h" to the normal spelling ("1h" / "1D" / "1h"), or null when it is not a timeframe. */
export function normTimeframe(tf: string): string | null {
  return Object.prototype.hasOwnProperty.call(TIMEFRAMES, tf) ? TIMEFRAMES[tf] : null;
}

/** Nominal length in seconds (a month counts as 30 days: only for comparing "longer than"). */
export function tfSeconds(tf: string): number {
  return SEC[normTimeframe(tf) ?? tf] ?? NaN;
}

/** Start of the bucket (of timeframe `tf`) that holds time `t`. */
export function bucketStart(t: number, tf: string): number {
  if (tf === "1D") return Math.floor(t / 86400) * 86400;
  if (tf === "1W") {
    // 1970-01-01 was a Thursday, so (day + 3) % 7 is 0 on Mondays
    const day = Math.floor(t / 86400);
    return (day - (((day + 3) % 7) + 7) % 7) * 86400;
  }
  if (tf === "1M") {
    const d = new Date(t * 1000);
    return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 1) / 1000;
  }
  const s = SEC[tf];
  return Math.floor(t / s) * s;
}

/** The time a bucket that starts at `start` ends (= the next bucket's start). */
export function bucketEnd(start: number, tf: string): number {
  if (tf === "1M") {
    const d = new Date(start * 1000);
    return Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1) / 1000;
  }
  return start + SEC[tf];
}

/** Resample bars (oldest first, `t` ascending) to the longer timeframe `tf` (normal spelling). */
export function resample(src: TCols, tf: string): TCols {
  const n = src.t.length;
  const o = new Float64Array(n);
  const h = new Float64Array(n);
  const l = new Float64Array(n);
  const c = new Float64Array(n);
  const v = new Float64Array(n);
  const t = new Float64Array(n);
  let k = -1;
  let curStart = NaN;
  let curEnd = NaN;
  for (let i = 0; i < n; i++) {
    const ti = src.t[i];
    // still inside the current bucket? (cheap check; only compute the bucket when we leave it)
    if (k < 0 || ti >= curEnd || ti < curStart) {
      curStart = bucketStart(ti, tf);
      curEnd = bucketEnd(curStart, tf);
      k++;
      o[k] = src.o[i];
      h[k] = src.h[i];
      l[k] = src.l[i];
      c[k] = src.c[i];
      v[k] = src.v[i];
      t[k] = curStart;
    } else {
      if (src.h[i] > h[k]) h[k] = src.h[i];
      if (src.l[i] < l[k]) l[k] = src.l[i];
      c[k] = src.c[i];
      v[k] += src.v[i];
    }
  }
  const m = k + 1;
  return { o: o.slice(0, m), h: h.slice(0, m), l: l.slice(0, m), c: c.slice(0, m), v: v.slice(0, m), t: t.slice(0, m) };
}
