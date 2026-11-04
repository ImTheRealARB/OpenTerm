/** Trend and overlay indicators (drawn on the price pane unless noted). */
import { bollinger, ema, sma, vwap } from "../indicators";
import { adx, atr, donchian, ichimoku, keltner, psar, supertrend } from "../studies";
import { type A, emaN, hi, lag, linreg, lo, map, nanArr, rmaN, smaN, sumN, wmaN, zip } from "./math";
import { type IndicatorDef, P } from "./types";

const t = (id: string, name: string, plain: string, params: IndicatorDef["params"], outputs: string[], fn: IndicatorDef["fn"], pane: "price" | "lower" = "price", category: IndicatorDef["category"] = "trend"): IndicatorDef => ({
  id, name, category, pane, params, outputs, plain, fn,
});

export function trima(a: A, n: number): A {
  const odd = n % 2 === 1;
  return smaN(smaN(a, odd ? (n + 1) / 2 : n / 2), odd ? (n + 1) / 2 : n / 2 + 1);
}

export function kama(c: A, n = 10, fast = 2, slow = 30): A {
  const out = nanArr(c.length);
  const f = 2 / (fast + 1);
  const s = 2 / (slow + 1);
  let prev = c[n - 1];
  for (let i = n; i < c.length; i++) {
    let vol = 0;
    for (let j = i - n + 1; j <= i; j++) vol += Math.abs(c[j] - c[j - 1]);
    const er = vol === 0 ? 0 : Math.abs(c[i] - c[i - n]) / vol;
    const sc = (er * (f - s) + s) ** 2;
    prev = prev + sc * (c[i] - prev);
    out[i] = prev;
  }
  return out;
}

export function alma(c: A, n = 9, offset = 0.85, sigma = 6): A {
  const out = nanArr(c.length);
  const m = offset * (n - 1);
  const s = n / sigma;
  const w = new Float64Array(n);
  let ws = 0;
  for (let j = 0; j < n; j++) {
    w[j] = Math.exp(-((j - m) ** 2) / (2 * s * s));
    ws += w[j];
  }
  for (let i = n - 1; i < c.length; i++) {
    let x = 0;
    for (let j = 0; j < n; j++) x += w[j] * c[i - n + 1 + j];
    out[i] = x / ws;
  }
  return out;
}

export function t3(c: A, n = 5, vf = 0.7): A {
  const e1 = emaN(c, n);
  const e2 = emaN(e1, n);
  const e3 = emaN(e2, n);
  const e4 = emaN(e3, n);
  const e5 = emaN(e4, n);
  const e6 = emaN(e5, n);
  const a = vf;
  const c1 = -a * a * a;
  const c2 = 3 * a * a + 3 * a * a * a;
  const c3 = -6 * a * a - 3 * a - 3 * a * a * a;
  const c4 = 1 + 3 * a + a * a * a + 3 * a * a;
  return map(c, (_, i) => c1 * e6[i] + c2 * e5[i] + c3 * e4[i] + c4 * e3[i]);
}

export function mcginley(c: A, n = 14): A {
  const out = nanArr(c.length);
  if (!c.length) return out;
  out[0] = c[0];
  for (let i = 1; i < c.length; i++) {
    const p = out[i - 1];
    out[i] = p + (c[i] - p) / (n * (c[i] / p) ** 4);
  }
  return out;
}

export function vwma(c: A, v: A, n: number): A {
  return zip(sumN(zip(c, v, (x, y) => x * y), n), sumN(v, n), (a, b) => (b === 0 ? NaN : a / b));
}

export function hma(c: A, n: number): A {
  const half = Math.max(1, Math.floor(n / 2));
  const raw = zip(wmaN(c, half), wmaN(c, n), (a, b) => 2 * a - b);
  return wmaN(raw, Math.max(1, Math.round(Math.sqrt(n))));
}

export function zlema(c: A, n: number): A {
  const k = Math.floor((n - 1) / 2);
  const l = lag(c, k);
  return emaN(zip(c, l, (x, y) => x + (x - y)), n);
}

/** Rolling median. */
export function medianN(a: A, n: number): A {
  const out = nanArr(a.length);
  const buf = new Float64Array(n);
  for (let i = n - 1; i < a.length; i++) {
    for (let j = 0; j < n; j++) buf[j] = a[i - n + 1 + j];
    buf.sort();
    out[i] = n % 2 ? buf[(n - 1) / 2] : (buf[n / 2 - 1] + buf[n / 2]) / 2;
  }
  return out;
}

/** Chande Kroll stop: long = highest(HH(p) - x*ATR(p), q); short = lowest(LL(p) + x*ATR(p), q). */
export function chandeKroll(h: A, l: A, c: A, p = 10, x = 1, q = 9) {
  const a = atr(h, l, c, p);
  const hh = hi(h, p);
  const ll = lo(l, p);
  const longRaw = zip(hh, a, (u, v) => u - x * v);
  const shortRaw = zip(ll, a, (u, v) => u + x * v);
  return { stopLong: hi(longRaw, q), stopShort: lo(shortRaw, q) };
}

/** Pivot points from the PREVIOUS bar's high, low, close. kind 0 classic, 1 fibonacci, 2 camarilla. */
export function pivots(h: A, l: A, c: A, kind: 0 | 1 | 2): A[] {
  const n = h.length;
  const out = Array.from({ length: kind === 0 ? 5 : kind === 1 ? 7 : 8 }, () => nanArr(n));
  for (let i = 1; i < n; i++) {
    const H = h[i - 1];
    const L = l[i - 1];
    const C = c[i - 1];
    const R = H - L;
    const P0 = (H + L + C) / 3;
    if (kind === 0) {
      [P0, 2 * P0 - L, 2 * P0 - H, P0 + R, P0 - R].forEach((v, k) => (out[k][i] = v));
    } else if (kind === 1) {
      [P0, P0 + 0.382 * R, P0 + 0.618 * R, P0 + R, P0 - 0.382 * R, P0 - 0.618 * R, P0 - R].forEach((v, k) => (out[k][i] = v));
    } else {
      const k = 1.1;
      [C + (k * R) / 12, C + (k * R) / 6, C + (k * R) / 4, C + (k * R) / 2, C - (k * R) / 12, C - (k * R) / 6, C - (k * R) / 4, C - (k * R) / 2].forEach((v, j) => (out[j][i] = v));
    }
  }
  return out;
}

export const TREND: IndicatorDef[] = [
  t("SMA", "Simple moving average", "The average close of the last N bars; smooths noise so the trend is easier to see.", [P("length", 20)], ["sma"], (c, p) => [sma(c.c, p[0])]),
  t("EMA", "Exponential moving average", "A moving average that weights recent bars more, so it reacts faster than SMA.", [P("length", 20)], ["ema"], (c, p) => [ema(c.c, p[0])]),
  t("WMA", "Weighted moving average", "A moving average where each newer bar counts a little more than the one before.", [P("length", 20)], ["wma"], (c, p) => [wmaN(c.c, p[0])]),
  t("SMMA", "Smoothed moving average (Wilder)", "A very slow moving average, the one Wilder used inside RSI and ATR.", [P("length", 14)], ["smma"], (c, p) => [rmaN(c.c, p[0])]),
  t("HMA", "Hull moving average", "A fast, low-lag moving average that still looks smooth.", [P("length", 21)], ["hma"], (c, p) => [hma(c.c, p[0])]),
  t("DEMA", "Double EMA", "Cuts the lag of an EMA by subtracting a second smoothing of itself.", [P("length", 20)], ["dema"], (c, p) => {
    const e1 = emaN(c.c, p[0]);
    return [zip(e1, emaN(e1, p[0]), (a, b) => 2 * a - b)];
  }),
  t("TEMA", "Triple EMA", "An even lower-lag cousin of the EMA, built from three smoothings.", [P("length", 20)], ["tema"], (c, p) => {
    const e1 = emaN(c.c, p[0]);
    const e2 = emaN(e1, p[0]);
    const e3 = emaN(e2, p[0]);
    return [map(e1, (_, i) => 3 * e1[i] - 3 * e2[i] + e3[i])];
  }),
  t("TRIMA", "Triangular moving average", "An average of an average: very smooth, puts most weight on the middle of the window.", [P("length", 20)], ["trima"], (c, p) => [trima(c.c, p[0])]),
  t("KAMA", "Kaufman adaptive MA", "A moving average that speeds up in clean trends and slows down in choppy markets.", [P("length", 10), P("fast", 2), P("slow", 30)], ["kama"], (c, p) => [kama(c.c, p[0], p[1], p[2])]),
  t("ZLEMA", "Zero-lag EMA", "An EMA that tries to remove its own delay by looking at the change over half its length.", [P("length", 20)], ["zlema"], (c, p) => [zlema(c.c, p[0])]),
  t("VWMA", "Volume-weighted MA", "A moving average where busy bars count more than quiet ones.", [P("length", 20)], ["vwma"], (c, p) => [vwma(c.c, c.v, p[0])]),
  t("ALMA", "Arnaud Legoux MA", "A smooth moving average shifted towards recent bars with a bell-shaped weighting.", [P("length", 9), { name: "offset", default: 0.85, min: 0, max: 1 }, P("sigma", 6, 1, 20)], ["alma"], (c, p) => [alma(c.c, p[0], p[1], p[2])]),
  t("T3", "Tillson T3", "A very smooth, low-lag moving average built from six EMAs.", [P("length", 5), { name: "volume factor", default: 0.7, min: 0, max: 1 }], ["t3"], (c, p) => [t3(c.c, p[0], p[1])]),
  t("MCGINLEY", "McGinley dynamic", "A moving average that adjusts its own speed to the market so it hugs price better.", [P("length", 14)], ["mcginley"], (c, p) => [mcginley(c.c, p[0])]),
  t("LSMA", "Linear regression line", "The end point of a best-fit straight line through the last N closes.", [P("length", 25)], ["linreg"], (c, p) => [linreg(c.c, p[0]).value]),
  t("BB", "Bollinger Bands", "A moving average with bands two standard deviations away; price near a band is stretched.", [P("length", 20), { name: "mult", default: 2, min: 0.1, max: 10 }], ["mid", "upper", "lower"], (c, p) => {
    const b = bollinger(c.c, p[0], p[1]);
    return [b.mid, b.upper, b.lower];
  }),
  t("ENV", "Moving average envelopes", "Two lines a fixed percent above and below a moving average.", [P("length", 20), { name: "percent", default: 2.5, min: 0.1, max: 25 }], ["mid", "upper", "lower"], (c, p) => {
    const m = smaN(c.c, p[0]);
    return [m, map(m, (x) => x * (1 + p[1] / 100)), map(m, (x) => x * (1 - p[1] / 100))];
  }),
  t("KELT", "Keltner Channel", "An EMA with bands set by average true range; a breakout above the top is strong momentum.", [P("length", 20), P("atr length", 10), { name: "mult", default: 2, min: 0.1, max: 10 }], ["mid", "upper", "lower"], (c, p) => {
    const k = keltner(c.h, c.l, c.c, p[0], p[1], p[2]);
    return [k.mid, k.upper, k.lower];
  }),
  t("DONCH", "Donchian Channel", "The highest high and lowest low of the last N bars; a close outside is a breakout.", [P("length", 20)], ["upper", "lower", "mid"], (c, p) => {
    const d = donchian(c.h, c.l, p[0]);
    return [d.upper, d.lower, d.mid];
  }),
  t("PRICECH", "Price channel", "The high and low of the previous N bars, not counting today, so a break is easy to spot.", [P("length", 20)], ["upper", "lower"], (c, p) => [lag(hi(c.h, p[0]), 1), lag(lo(c.l, p[0]), 1)]),
  t("SUPERTREND", "SuperTrend", "A line under price in uptrends and over it in downtrends; a flip signals a trend change.", [P("length", 10), { name: "mult", default: 3, min: 0.5, max: 10 }], ["line", "dir"], (c, p) => {
    const s = supertrend(c.h, c.l, c.c, p[0], p[1]);
    return [s.line, s.dir];
  }),
  t("PSAR", "Parabolic SAR", "Dots that trail price and flip sides when the trend reverses; handy for stop placement.", [{ name: "step", default: 0.02, min: 0.001, max: 0.5 }, { name: "max", default: 0.2, min: 0.01, max: 1 }], ["sar"], (c, p) => [psar(c.h, c.l, p[0], p[1])]),
  t("ICHIMOKU", "Ichimoku Cloud", "Five lines that show trend, momentum and support in one view; price above the cloud is bullish.", [P("tenkan", 9), P("kijun", 26), P("senkou B", 52), P("shift", 26)], ["tenkan", "kijun", "spanA", "spanB", "chikou"], (c, p) => {
    const i = ichimoku(c.h, c.l, c.c, p[0], p[1], p[2], p[3]);
    return [i.tenkan, i.kijun, i.spanA, i.spanB, i.chikou];
  }),
  t("VWAP", "VWAP", "The average price paid today weighted by volume; institutions use it as a fair-value line.", [], ["vwap"], (c) => {
    const tt = c.t ?? Float64Array.from({ length: c.c.length }, (_, i) => i * 60);
    return [vwap(tt, c.h, c.l, c.c, c.v)];
  }),
  t("CHANDELIER", "Chandelier exit", "A trailing stop hung from the highest high (long) or lowest low (short) by a multiple of ATR.", [P("length", 22), { name: "mult", default: 3, min: 0.5, max: 10 }], ["long", "short"], (c, p) => {
    const a = atr(c.h, c.l, c.c, p[0]);
    return [zip(hi(c.h, p[0]), a, (x, y) => x - p[1] * y), zip(lo(c.l, p[0]), a, (x, y) => x + p[1] * y)];
  }),
  t("CHANDEKROLL", "Chande Kroll stop", "Two trailing stop lines from ATR; close below the long stop means the uptrend is in doubt.", [P("length", 10), { name: "mult", default: 1, min: 0.1, max: 10 }, P("smooth", 9)], ["long", "short"], (c, p) => {
    const r = chandeKroll(c.h, c.l, c.c, p[0], p[1], p[2]);
    return [r.stopLong, r.stopShort];
  }),
  t("ATRBANDS", "ATR bands", "Bands around the close at a multiple of the average true range.", [P("length", 14), { name: "mult", default: 2, min: 0.1, max: 10 }], ["upper", "lower"], (c, p) => {
    const a = atr(c.h, c.l, c.c, p[0]);
    return [zip(c.c, a, (x, y) => x + p[1] * y), zip(c.c, a, (x, y) => x - p[1] * y)];
  }),
  t("PIVOT", "Pivot points (classic)", "Support and resistance levels worked out from the previous bar.", [], ["pivot", "r1", "s1", "r2", "s2"], (c) => pivots(c.h, c.l, c.c, 0)),
  t("PIVOTFIB", "Pivot points (Fibonacci)", "Pivot levels spaced at Fibonacci ratios of the previous bar's range.", [], ["pivot", "r1", "r2", "r3", "s1", "s2", "s3"], (c) => pivots(c.h, c.l, c.c, 1)),
  t("PIVOTCAM", "Pivot points (Camarilla)", "Tight pivot levels around the previous close; popular for day trading reversals.", [], ["r1", "r2", "r3", "r4", "s1", "s2", "s3", "s4"], (c) => pivots(c.h, c.l, c.c, 2)),
  t("HAC", "Heikin-Ashi close", "The average of open, high, low and close; a smoother version of price.", [], ["close"], (c) => [zip(zip(c.o, c.h, (a, b) => a + b), zip(c.l, c.c, (a, b) => a + b), (a, b) => (a + b) / 4)]),
  t("HAO", "Heikin-Ashi open", "The Heikin-Ashi candle open: the midpoint of the previous Heikin-Ashi candle.", [], ["open"], (c) => {
    const n = c.c.length;
    const out = nanArr(n);
    const hac = (i: number) => (c.o[i] + c.h[i] + c.l[i] + c.c[i]) / 4;
    if (n) out[0] = (c.o[0] + c.c[0]) / 2;
    for (let i = 1; i < n; i++) out[i] = (out[i - 1] + hac(i - 1)) / 2;
    return [out];
  }),
  t("TYPPRICE", "Typical price", "The average of high, low and close; a fair single number for the bar.", [], ["tp"], (c) => [map(c.c, (x, i) => (c.h[i] + c.l[i] + x) / 3)]),
  t("MEDPRICE", "Median price", "The midpoint of the bar's high and low.", [], ["mp"], (c) => [map(c.c, (_, i) => (c.h[i] + c.l[i]) / 2)]),
  t("WCLPRICE", "Weighted close", "High plus low plus twice the close, divided by four; leans towards the close.", [], ["wc"], (c) => [map(c.c, (x, i) => (c.h[i] + c.l[i] + 2 * x) / 4)]),
  t("HIGHEST", "Highest high", "The highest high of the last N bars.", [P("length", 20)], ["highest"], (c, p) => [hi(c.h, p[0])], "price", "other"),
  t("LOWEST", "Lowest low", "The lowest low of the last N bars.", [P("length", 20)], ["lowest"], (c, p) => [lo(c.l, p[0])], "price", "other"),
  t("MEDIAN", "Rolling median", "The middle close of the last N bars; ignores single-bar spikes.", [P("length", 20)], ["median"], (c, p) => [medianN(c.c, p[0])]),
  t("LRSLOPE", "Linear regression slope", "How fast the best-fit line is rising or falling per bar; above zero means up.", [P("length", 25)], ["slope"], (c, p) => [linreg(c.c, p[0]).slope], "lower"),
  t("LRINTERCEPT", "Linear regression intercept", "Where the best-fit line starts at the beginning of the window.", [P("length", 25)], ["intercept"], (c, p) => [linreg(c.c, p[0]).intercept]),
  t("LRR2", "Linear regression R-squared", "How well a straight line fits price: near 1 is a clean trend, near 0 is noise.", [P("length", 25)], ["r2"], (c, p) => [linreg(c.c, p[0]).r2], "lower", "other"),
  t("ADX", "ADX (trend strength)", "Measures how strong a trend is, not its direction; above 25 is usually a real trend.", [P("length", 14)], ["adx", "+di", "-di"], (c, p) => {
    const r = adx(c.h, c.l, c.c, p[0]);
    return [r.adx, r.pdi, r.mdi];
  }, "lower"),
  t("DMI", "Directional movement (+DI/-DI)", "Two lines showing whether buyers or sellers are pushing price harder.", [P("length", 14)], ["+di", "-di"], (c, p) => {
    const r = adx(c.h, c.l, c.c, p[0]);
    return [r.pdi, r.mdi];
  }, "lower"),
  t("ADXR", "ADX rating", "ADX averaged with its value N bars ago; a calmer read of trend strength.", [P("length", 14)], ["adxr"], (c, p) => {
    const a = adx(c.h, c.l, c.c, p[0]).adx;
    const l = lag(a, p[0]);
    return [zip(a, l, (x, y) => (x + y) / 2)];
  }, "lower"),
  t("AROON", "Aroon", "Counts how recently the highest high and lowest low happened; both near 100 / 0 shows a strong trend.", [P("length", 25)], ["up", "down"], (c, p) => aroon(c.h, c.l, p[0]), "lower"),
  t("AROONOSC", "Aroon oscillator", "Aroon Up minus Aroon Down: above zero is an uptrend, below zero a downtrend.", [P("length", 25)], ["osc"], (c, p) => {
    const [u, d] = aroon(c.h, c.l, p[0]);
    return [zip(u, d, (x, y) => x - y)];
  }, "lower"),
  t("VORTEX", "Vortex indicator", "Two lines that cross when a new trend starts: +VI above -VI is up.", [P("length", 14)], ["+vi", "-vi"], (c, p) => vortex(c.h, c.l, c.c, p[0]), "lower"),
];

export function aroon(h: A, l: A, n: number): A[] {
  const up = nanArr(h.length);
  const dn = nanArr(h.length);
  for (let i = n; i < h.length; i++) {
    let bh = i - n;
    let bl = i - n;
    for (let j = i - n; j <= i; j++) {
      if (h[j] >= h[bh]) bh = j;
      if (l[j] <= l[bl]) bl = j;
    }
    up[i] = (100 * (n - (i - bh))) / n;
    dn[i] = (100 * (n - (i - bl))) / n;
  }
  return [up, dn];
}

export function vortex(h: A, l: A, c: A, n: number): A[] {
  const len = h.length;
  const vmp = nanArr(len);
  const vmm = nanArr(len);
  const tr = nanArr(len);
  for (let i = 1; i < len; i++) {
    vmp[i] = Math.abs(h[i] - l[i - 1]);
    vmm[i] = Math.abs(l[i] - h[i - 1]);
    tr[i] = Math.max(h[i] - l[i], Math.abs(h[i] - c[i - 1]), Math.abs(l[i] - c[i - 1]));
  }
  const st = sumN(tr, n);
  return [zip(sumN(vmp, n), st, (a, b) => a / b), zip(sumN(vmm, n), st, (a, b) => a / b)];
}
