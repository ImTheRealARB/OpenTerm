/**
 * Phase 19 studies on Float64Arrays (NaN = not enough data yet). Pure: run in the indicator worker and in unit tests.
 * Conventions: Wilder smoothing for ATR / ADX, population mean deviation for CCI, flat windows give the mid value (50 / -50), not NaN.
 */
const nanArr = (n: number) => new Float64Array(n).fill(NaN);

/** SMA-seeded EMA (same as indicators.ts `ema`; kept here so this file has no import cycle with `compute`). */
function ema(src: Float64Array, n: number): Float64Array {
  const out = nanArr(src.length);
  if (src.length < n) return out;
  const k = 2 / (n + 1);
  let prev = 0;
  for (let i = 0; i < n; i++) prev += src[i];
  prev /= n;
  out[n - 1] = prev;
  for (let i = n; i < src.length; i++) {
    prev = src[i] * k + prev * (1 - k);
    out[i] = prev;
  }
  return out;
}

function trueRange(h: Float64Array, l: Float64Array, c: Float64Array): Float64Array {
  const tr = new Float64Array(h.length);
  for (let i = 0; i < h.length; i++) {
    tr[i] = i === 0 ? h[i] - l[i] : Math.max(h[i] - l[i], Math.abs(h[i] - c[i - 1]), Math.abs(l[i] - c[i - 1]));
  }
  return tr;
}

/** Wilder's average true range. */
export function atr(h: Float64Array, l: Float64Array, c: Float64Array, n = 14): Float64Array {
  const out = nanArr(h.length);
  if (h.length < n) return out;
  const tr = trueRange(h, l, c);
  let prev = 0;
  for (let i = 0; i < n; i++) prev += tr[i];
  prev /= n;
  out[n - 1] = prev;
  for (let i = n; i < h.length; i++) {
    prev = (prev * (n - 1) + tr[i]) / n;
    out[i] = prev;
  }
  return out;
}

function highest(src: Float64Array, i: number, n: number): number {
  let m = -Infinity;
  for (let j = i - n + 1; j <= i; j++) if (src[j] > m) m = src[j];
  return m;
}
function lowest(src: Float64Array, i: number, n: number): number {
  let m = Infinity;
  for (let j = i - n + 1; j <= i; j++) if (src[j] < m) m = src[j];
  return m;
}

export function stoch(h: Float64Array, l: Float64Array, c: Float64Array, kN = 14, dN = 3) {
  const k = nanArr(c.length);
  const d = nanArr(c.length);
  for (let i = kN - 1; i < c.length; i++) {
    const hh = highest(h, i, kN);
    const ll = lowest(l, i, kN);
    k[i] = hh === ll ? 50 : (100 * (c[i] - ll)) / (hh - ll);
  }
  for (let i = kN - 1 + dN - 1; i < c.length; i++) {
    let s = 0;
    for (let j = i - dN + 1; j <= i; j++) s += k[j];
    d[i] = s / dN;
  }
  return { k, d };
}

/** Wilder's ADX with +DI / -DI. First ADX value is at index 2n - 1. */
export function adx(h: Float64Array, l: Float64Array, c: Float64Array, n = 14) {
  const len = c.length;
  const out = { adx: nanArr(len), pdi: nanArr(len), mdi: nanArr(len) };
  if (len < 2 * n) return out;
  const tr = trueRange(h, l, c);
  const pdm = new Float64Array(len);
  const mdm = new Float64Array(len);
  for (let i = 1; i < len; i++) {
    const up = h[i] - h[i - 1];
    const dn = l[i - 1] - l[i];
    pdm[i] = up > dn && up > 0 ? up : 0;
    mdm[i] = dn > up && dn > 0 ? dn : 0;
  }
  let sTr = 0;
  let sP = 0;
  let sM = 0;
  for (let i = 1; i <= n; i++) {
    sTr += tr[i];
    sP += pdm[i];
    sM += mdm[i];
  }
  const dx = nanArr(len);
  const di = (i: number) => {
    const p = sTr === 0 ? 0 : (100 * sP) / sTr;
    const m = sTr === 0 ? 0 : (100 * sM) / sTr;
    out.pdi[i] = p;
    out.mdi[i] = m;
    dx[i] = p + m === 0 ? 0 : (100 * Math.abs(p - m)) / (p + m);
  };
  di(n);
  for (let i = n + 1; i < len; i++) {
    sTr = sTr - sTr / n + tr[i];
    sP = sP - sP / n + pdm[i];
    sM = sM - sM / n + mdm[i];
    di(i);
  }
  let a = 0;
  for (let i = n; i < 2 * n; i++) a += dx[i];
  a /= n;
  out.adx[2 * n - 1] = a;
  for (let i = 2 * n; i < len; i++) {
    a = (a * (n - 1) + dx[i]) / n;
    out.adx[i] = a;
  }
  return out;
}

export function obv(c: Float64Array, v: Float64Array): Float64Array {
  const out = new Float64Array(c.length);
  for (let i = 1; i < c.length; i++) out[i] = out[i - 1] + (c[i] > c[i - 1] ? v[i] : c[i] < c[i - 1] ? -v[i] : 0);
  return out;
}

export function cci(h: Float64Array, l: Float64Array, c: Float64Array, n = 20): Float64Array {
  const out = nanArr(c.length);
  const tp = new Float64Array(c.length);
  for (let i = 0; i < c.length; i++) tp[i] = (h[i] + l[i] + c[i]) / 3;
  for (let i = n - 1; i < c.length; i++) {
    let m = 0;
    for (let j = i - n + 1; j <= i; j++) m += tp[j];
    m /= n;
    let dev = 0;
    for (let j = i - n + 1; j <= i; j++) dev += Math.abs(tp[j] - m);
    dev /= n;
    out[i] = dev === 0 ? 0 : (tp[i] - m) / (0.015 * dev);
  }
  return out;
}

export function willr(h: Float64Array, l: Float64Array, c: Float64Array, n = 14): Float64Array {
  const out = nanArr(c.length);
  for (let i = n - 1; i < c.length; i++) {
    const hh = highest(h, i, n);
    const ll = lowest(l, i, n);
    out[i] = hh === ll ? -50 : (-100 * (hh - c[i])) / (hh - ll);
  }
  return out;
}

export function mfi(h: Float64Array, l: Float64Array, c: Float64Array, v: Float64Array, n = 14): Float64Array {
  const out = nanArr(c.length);
  const tp = new Float64Array(c.length);
  for (let i = 0; i < c.length; i++) tp[i] = (h[i] + l[i] + c[i]) / 3;
  for (let i = n; i < c.length; i++) {
    let pos = 0;
    let neg = 0;
    for (let j = i - n + 1; j <= i; j++) {
      const flow = tp[j] * v[j];
      if (tp[j] > tp[j - 1]) pos += flow;
      else if (tp[j] < tp[j - 1]) neg += flow;
    }
    out[i] = pos === 0 && neg === 0 ? 50 : neg === 0 ? 100 : 100 - 100 / (1 + pos / neg);
  }
  return out;
}

/** Keltner channel: EMA(n) +/- mult x ATR(atrN). */
export function keltner(h: Float64Array, l: Float64Array, c: Float64Array, n = 20, atrN = 10, mult = 2) {
  const mid = ema(c, n);
  const a = atr(h, l, c, atrN);
  const upper = nanArr(c.length);
  const lower = nanArr(c.length);
  for (let i = 0; i < c.length; i++) {
    if (Number.isFinite(mid[i]) && Number.isFinite(a[i])) {
      upper[i] = mid[i] + mult * a[i];
      lower[i] = mid[i] - mult * a[i];
    }
  }
  return { mid, upper, lower };
}

export function donchian(h: Float64Array, l: Float64Array, n = 20) {
  const upper = nanArr(h.length);
  const lower = nanArr(h.length);
  const mid = nanArr(h.length);
  for (let i = n - 1; i < h.length; i++) {
    upper[i] = highest(h, i, n);
    lower[i] = lowest(l, i, n);
    mid[i] = (upper[i] + lower[i]) / 2;
  }
  return { upper, lower, mid };
}

/** SuperTrend. `dir` is 1 (up, line under price) or -1 (down, line over price), NaN before ATR exists. */
export function supertrend(h: Float64Array, l: Float64Array, c: Float64Array, n = 10, mult = 3) {
  const len = c.length;
  const line = nanArr(len);
  const dir = nanArr(len);
  const a = atr(h, l, c, n);
  let fu = NaN;
  let fl = NaN;
  let d = 1;
  for (let i = n - 1; i < len; i++) {
    const hl2 = (h[i] + l[i]) / 2;
    const bu = hl2 + mult * a[i];
    const bl = hl2 - mult * a[i];
    if (i === n - 1) {
      fu = bu;
      fl = bl;
      d = c[i] >= hl2 ? 1 : -1;
    } else {
      const pfu = fu;
      const pfl = fl;
      fu = bu < pfu || c[i - 1] > pfu ? bu : pfu;
      fl = bl > pfl || c[i - 1] < pfl ? bl : pfl;
      if (d === 1 && c[i] < fl) d = -1;
      else if (d === -1 && c[i] > fu) d = 1;
    }
    dir[i] = d;
    line[i] = d === 1 ? fl : fu;
  }
  return { line, dir };
}

/** Wilder's parabolic SAR. Index 0 has no value. */
export function psar(h: Float64Array, l: Float64Array, step = 0.02, max = 0.2): Float64Array {
  const len = h.length;
  const out = nanArr(len);
  if (len < 2) return out;
  let up = h[1] + l[1] >= h[0] + l[0];
  let sar = up ? l[0] : h[0];
  let ep = up ? h[0] : l[0];
  let af = step;
  for (let i = 1; i < len; i++) {
    sar = sar + af * (ep - sar);
    if (up) {
      sar = Math.min(sar, l[i - 1], i >= 2 ? l[i - 2] : Infinity);
      if (l[i] < sar) {
        up = false;
        sar = ep;
        ep = l[i];
        af = step;
      } else if (h[i] > ep) {
        ep = h[i];
        af = Math.min(af + step, max);
      }
    } else {
      sar = Math.max(sar, h[i - 1], i >= 2 ? h[i - 2] : -Infinity);
      if (h[i] > sar) {
        up = true;
        sar = ep;
        ep = h[i];
        af = step;
      } else if (l[i] < ep) {
        ep = l[i];
        af = Math.min(af + step, max);
      }
    }
    out[i] = sar;
  }
  return out;
}

/**
 * Ichimoku Kinko Hyo. spanA / spanB are displaced `shift` bars forward and chikou `shift` bars back, all kept aligned with the
 * input bars: the part of the cloud that falls past the last bar is not returned (it would need future timestamps).
 */
export function ichimoku(h: Float64Array, l: Float64Array, c: Float64Array, tn = 9, kn = 26, bn = 52, shift = 26) {
  const len = c.length;
  const mid = (n: number) => {
    const r = nanArr(len);
    for (let i = n - 1; i < len; i++) r[i] = (highest(h, i, n) + lowest(l, i, n)) / 2;
    return r;
  };
  const tenkan = mid(tn);
  const kijun = mid(kn);
  const rawB = mid(bn);
  const spanA = nanArr(len);
  const spanB = nanArr(len);
  const chikou = nanArr(len);
  for (let i = 0; i < len; i++) {
    const j = i + shift;
    if (j < len) {
      if (Number.isFinite(tenkan[i]) && Number.isFinite(kijun[i])) spanA[j] = (tenkan[i] + kijun[i]) / 2;
      spanB[j] = rawB[i];
    }
    if (i + shift < len) chikou[i] = c[i + shift];
  }
  return { tenkan, kijun, spanA, spanB, chikou };
}
