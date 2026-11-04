/**
 * Building blocks for the indicator library. Pure functions on Float64Array; NaN = not enough data yet.
 * Every helper tolerates LEADING NaN in its input (a composite such as TRIX feeds one helper's output to the next).
 * Written from the formula definitions; no third-party code.
 */
export type A = Float64Array;
export const nanArr = (n: number): A => new Float64Array(n).fill(NaN);

export function firstFinite(a: A): number {
  for (let i = 0; i < a.length; i++) if (Number.isFinite(a[i])) return i;
  return a.length;
}

export function smaN(a: A, n: number): A {
  const out = nanArr(a.length);
  const f = firstFinite(a);
  let sum = 0;
  for (let i = f; i < a.length; i++) {
    sum += a[i];
    if (i - f >= n) sum -= a[i - n];
    if (i - f >= n - 1) out[i] = sum / n;
  }
  return out;
}

/** EMA seeded with the SMA of the first n valid values. */
export function emaN(a: A, n: number): A {
  const out = nanArr(a.length);
  const f = firstFinite(a);
  if (a.length - f < n) return out;
  const k = 2 / (n + 1);
  let prev = 0;
  for (let i = f; i < f + n; i++) prev += a[i];
  prev /= n;
  out[f + n - 1] = prev;
  for (let i = f + n; i < a.length; i++) {
    prev = a[i] * k + prev * (1 - k);
    out[i] = prev;
  }
  return out;
}

/** Wilder smoothing (alpha = 1/n), seeded with the SMA of the first n valid values. */
export function rmaN(a: A, n: number): A {
  const out = nanArr(a.length);
  const f = firstFinite(a);
  if (a.length - f < n) return out;
  let prev = 0;
  for (let i = f; i < f + n; i++) prev += a[i];
  prev /= n;
  out[f + n - 1] = prev;
  for (let i = f + n; i < a.length; i++) {
    prev = (prev * (n - 1) + a[i]) / n;
    out[i] = prev;
  }
  return out;
}

export function wmaN(a: A, n: number): A {
  const out = nanArr(a.length);
  const den = (n * (n + 1)) / 2;
  for (let i = n - 1; i < a.length; i++) {
    let s = 0;
    for (let j = 0; j < n; j++) s += a[i - n + 1 + j] * (j + 1);
    out[i] = s / den; // a NaN inside the window propagates
  }
  return out;
}

export function hi(a: A, n: number): A {
  const out = nanArr(a.length);
  for (let i = n - 1; i < a.length; i++) {
    let m = -Infinity;
    for (let j = i - n + 1; j <= i; j++) m = Math.max(m, a[j]);
    out[i] = m;
  }
  return out;
}

export function lo(a: A, n: number): A {
  const out = nanArr(a.length);
  for (let i = n - 1; i < a.length; i++) {
    let m = Infinity;
    for (let j = i - n + 1; j <= i; j++) m = Math.min(m, a[j]);
    out[i] = m;
  }
  return out;
}

/** Rolling sum. */
export function sumN(a: A, n: number): A {
  const out = nanArr(a.length);
  for (let i = n - 1; i < a.length; i++) {
    let s = 0;
    for (let j = i - n + 1; j <= i; j++) s += a[j];
    out[i] = s;
  }
  return out;
}

/** Rolling population standard deviation. */
export function stdN(a: A, n: number): A {
  const out = nanArr(a.length);
  const m = smaN(a, n);
  for (let i = n - 1; i < a.length; i++) {
    if (!Number.isFinite(m[i])) continue;
    let ss = 0;
    for (let j = i - n + 1; j <= i; j++) ss += (a[j] - m[i]) ** 2;
    out[i] = Math.sqrt(ss / n);
  }
  return out;
}

export function lag(a: A, k: number): A {
  const out = nanArr(a.length);
  for (let i = k; i < a.length; i++) out[i] = a[i - k];
  return out;
}

export function diff(a: A, k = 1): A {
  const out = nanArr(a.length);
  for (let i = k; i < a.length; i++) out[i] = a[i] - a[i - k];
  return out;
}

export function map(a: A, f: (x: number, i: number) => number): A {
  const out = new Float64Array(a.length);
  for (let i = 0; i < a.length; i++) out[i] = f(a[i], i);
  return out;
}

export function zip(a: A, b: A, f: (x: number, y: number, i: number) => number): A {
  const out = new Float64Array(a.length);
  for (let i = 0; i < a.length; i++) out[i] = f(a[i], b[i], i);
  return out;
}

export function cumsum(a: A): A {
  const out = nanArr(a.length);
  let s = 0;
  for (let i = 0; i < a.length; i++) {
    if (!Number.isFinite(a[i])) continue;
    s += a[i];
    out[i] = s;
  }
  return out;
}

export function trueRange(h: A, l: A, c: A): A {
  const tr = new Float64Array(h.length);
  for (let i = 0; i < h.length; i++) tr[i] = i === 0 ? h[i] - l[i] : Math.max(h[i] - l[i], Math.abs(h[i] - c[i - 1]), Math.abs(l[i] - c[i - 1]));
  return tr;
}

/** Least-squares line over the last n values of a, x = 0..n-1. Returns slope, intercept at x = 0, value at the last bar, r squared. */
export function linreg(a: A, n: number) {
  const len = a.length;
  const slope = nanArr(len);
  const intercept = nanArr(len);
  const value = nanArr(len);
  const r2 = nanArr(len);
  const sx = (n * (n - 1)) / 2;
  const sxx = ((n - 1) * n * (2 * n - 1)) / 6;
  const den = n * sxx - sx * sx;
  for (let i = n - 1; i < len; i++) {
    let sy = 0;
    let sxy = 0;
    let syy = 0;
    for (let j = 0; j < n; j++) {
      const y = a[i - n + 1 + j];
      sy += y;
      sxy += j * y;
      syy += y * y;
    }
    const b = (n * sxy - sx * sy) / den;
    const a0 = (sy - b * sx) / n;
    slope[i] = b;
    intercept[i] = a0;
    value[i] = a0 + b * (n - 1);
    const vy = n * syy - sy * sy;
    r2[i] = vy === 0 ? 0 : (n * sxy - sx * sy) ** 2 / (den * vy);
  }
  return { slope, intercept, value, r2 };
}
