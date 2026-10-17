/**
 * Indicator math on Float64Arrays. NaN marks "not enough data yet". Pure functions: they run in a
 * Web Worker in the app and directly in unit tests.
 */

export function sma(src: Float64Array, n: number): Float64Array {
  const out = new Float64Array(src.length).fill(NaN);
  let sum = 0;
  for (let i = 0; i < src.length; i++) {
    sum += src[i];
    if (i >= n) sum -= src[i - n];
    if (i >= n - 1) out[i] = sum / n;
  }
  return out;
}

export function ema(src: Float64Array, n: number): Float64Array {
  const out = new Float64Array(src.length).fill(NaN);
  if (src.length < n) return out;
  const k = 2 / (n + 1);
  let seed = 0;
  for (let i = 0; i < n; i++) seed += src[i];
  let prev = seed / n;
  out[n - 1] = prev;
  for (let i = n; i < src.length; i++) {
    prev = src[i] * k + prev * (1 - k);
    out[i] = prev;
  }
  return out;
}

export function bollinger(src: Float64Array, n = 20, k = 2) {
  const mid = sma(src, n);
  const upper = new Float64Array(src.length).fill(NaN);
  const lower = new Float64Array(src.length).fill(NaN);
  for (let i = n - 1; i < src.length; i++) {
    let ss = 0;
    for (let j = i - n + 1; j <= i; j++) ss += (src[j] - mid[i]) ** 2;
    const sd = Math.sqrt(ss / n); // population SD, the usual convention
    upper[i] = mid[i] + k * sd;
    lower[i] = mid[i] - k * sd;
  }
  return { mid, upper, lower };
}

/** Wilder's RSI. */
export function rsi(src: Float64Array, n = 14): Float64Array {
  const out = new Float64Array(src.length).fill(NaN);
  if (src.length <= n) return out;
  let gain = 0;
  let loss = 0;
  for (let i = 1; i <= n; i++) {
    const d = src[i] - src[i - 1];
    if (d > 0) gain += d;
    else loss -= d;
  }
  gain /= n;
  loss /= n;
  out[n] = loss === 0 ? 100 : 100 - 100 / (1 + gain / loss);
  for (let i = n + 1; i < src.length; i++) {
    const d = src[i] - src[i - 1];
    gain = (gain * (n - 1) + Math.max(d, 0)) / n;
    loss = (loss * (n - 1) + Math.max(-d, 0)) / n;
    out[i] = loss === 0 ? 100 : 100 - 100 / (1 + gain / loss);
  }
  return out;
}

export function macd(src: Float64Array, fast = 12, slow = 26, signal = 9) {
  const f = ema(src, fast);
  const s = ema(src, slow);
  const line = new Float64Array(src.length).fill(NaN);
  for (let i = 0; i < src.length; i++) line[i] = f[i] - s[i];
  const start = slow - 1;
  const sig = new Float64Array(src.length).fill(NaN);
  if (src.length >= start + signal) {
    const tail = ema(line.subarray(start), signal);
    sig.set(tail, start);
  }
  const hist = new Float64Array(src.length).fill(NaN);
  for (let i = 0; i < src.length; i++) hist[i] = line[i] - sig[i];
  return { line, signal: sig, hist };
}

/** Session VWAP: resets when the gap between bars exceeds `sessionGapS` (a new trading day). */
export function vwap(t: Float64Array, h: Float64Array, l: Float64Array, c: Float64Array, v: Float64Array, sessionGapS = 4 * 3600) {
  const out = new Float64Array(c.length).fill(NaN);
  let pv = 0;
  let vv = 0;
  for (let i = 0; i < c.length; i++) {
    if (i > 0 && t[i] - t[i - 1] > sessionGapS) {
      pv = 0;
      vv = 0;
    }
    const vol = Number.isFinite(v[i]) ? v[i] : 0;
    pv += ((h[i] + l[i] + c[i]) / 3) * vol;
    vv += vol;
    out[i] = vv > 0 ? pv / vv : NaN;
  }
  return out;
}

export const INDICATORS = ["SMA20", "SMA50", "EMA20", "BB", "RSI", "MACD", "VWAP"] as const;
export type IndicatorName = (typeof INDICATORS)[number];

export interface Series {
  t: Float64Array;
  h: Float64Array;
  l: Float64Array;
  c: Float64Array;
  v: Float64Array;
}

/** Computes the requested indicators; every output is a Float64Array aligned with the input bars. */
export function compute(s: Series, which: IndicatorName[]): Record<string, Float64Array> {
  const out: Record<string, Float64Array> = {};
  for (const w of which) {
    if (w === "SMA20") out.SMA20 = sma(s.c, 20);
    else if (w === "SMA50") out.SMA50 = sma(s.c, 50);
    else if (w === "EMA20") out.EMA20 = ema(s.c, 20);
    else if (w === "BB") {
      const b = bollinger(s.c, 20, 2);
      out.BB_MID = b.mid;
      out.BB_UP = b.upper;
      out.BB_LO = b.lower;
    } else if (w === "RSI") out.RSI = rsi(s.c, 14);
    else if (w === "MACD") {
      const m = macd(s.c);
      out.MACD = m.line;
      out.MACD_SIG = m.signal;
      out.MACD_HIST = m.hist;
    } else if (w === "VWAP") out.VWAP = vwap(s.t, s.h, s.l, s.c, s.v);
  }
  return out;
}
