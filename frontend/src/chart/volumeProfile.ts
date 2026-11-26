/**
 * Phase 23: volume profile (volume at price). Pure: the indicators worker and vitest both run it.
 *
 * Bars do not say at which prices their volume traded, so each bar's volume is spread EVENLY over its high-low range
 * (the usual estimate; the chart labels it "ESTIMATED FROM <interval> BARS"). A bar with high == low puts all its volume
 * in one row. Crypto profiles built from real trades skip the estimate (`fromTrades`).
 *
 * Terms (each named once on screen through the glossary):
 *   POC  point of control: the price row with the most volume.
 *   VA   value area: the rows around the POC holding `vaPct` (70% by default) of the volume. Built the standard way:
 *        start at the POC, then repeatedly add the neighbouring row (above or below) with more volume.
 *   HVN / LVN  high / low volume nodes: rows that are a local maximum / minimum of the profile (over +-2 rows) and stand
 *        out from the average row (HVN above 1.5x the mean, LVN below 0.5x the mean but not empty).
 */
export interface Profile {
  /** Price of the bottom of row 0, and the height of one row. Row i covers [lo + i*step, lo + (i+1)*step). */
  lo: number;
  step: number;
  vol: Float64Array;
  total: number;
  poc: number; // row index
  vaLo: number; // row index (inclusive)
  vaHi: number; // row index (inclusive)
  hvn: number[];
  lvn: number[];
}

export const DEFAULT_ROWS = 48;
export const DEFAULT_VA = 0.7;

/** The profile of bars [from, to) (indexes into the arrays). Null when they hold no volume or no finite range. */
export function volumeProfile(h: Float64Array, l: Float64Array, v: Float64Array, from: number, to: number, rows = DEFAULT_ROWS, vaPct = DEFAULT_VA): Profile | null {
  let lo = Infinity;
  let hi = -Infinity;
  for (let i = from; i < to; i++) {
    if (!(v[i] > 0) || !Number.isFinite(h[i]) || !Number.isFinite(l[i])) continue;
    if (l[i] < lo) lo = l[i];
    if (h[i] > hi) hi = h[i];
  }
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return null;
  // One price for every bar (a flat market): one row holds everything.
  const step = hi > lo ? (hi - lo) / rows : 1;
  const n = hi > lo ? rows : 1;
  const vol = new Float64Array(n);
  let total = 0;
  for (let i = from; i < to; i++) {
    const vi = v[i];
    if (!(vi > 0) || !Number.isFinite(h[i]) || !Number.isFinite(l[i])) continue;
    total += vi;
    const a = Math.min(n - 1, Math.floor((l[i] - lo) / step));
    const b = Math.min(n - 1, Math.floor((h[i] - lo) / step));
    if (a === b) {
      vol[a] += vi;
      continue;
    }
    // Spread by the share of the bar's range that falls in each row (the end rows are partly covered).
    const span = h[i] - l[i];
    for (let r = a; r <= b; r++) {
      const top = Math.min(h[i], lo + (r + 1) * step);
      const bot = Math.max(l[i], lo + r * step);
      if (top > bot) vol[r] += (vi * (top - bot)) / span;
    }
  }
  let poc = 0;
  for (let r = 1; r < n; r++) if (vol[r] > vol[poc]) poc = r;
  // Value area: grow from the POC towards the heavier neighbour until it holds vaPct of the volume.
  let vaLo = poc;
  let vaHi = poc;
  let inVa = vol[poc];
  while (inVa < total * vaPct && (vaLo > 0 || vaHi < n - 1)) {
    const below = vaLo > 0 ? vol[vaLo - 1] : -1;
    const above = vaHi < n - 1 ? vol[vaHi + 1] : -1;
    if (above >= below) inVa += vol[++vaHi];
    else inVa += vol[--vaLo];
  }
  const mean = total / n;
  const hvn: number[] = [];
  const lvn: number[] = [];
  for (let r = 0; r < n; r++) {
    let max = true;
    let min = true;
    for (let k = Math.max(0, r - 2); k <= Math.min(n - 1, r + 2); k++) {
      if (k === r) continue;
      if (vol[k] > vol[r]) max = false;
      if (vol[k] < vol[r]) min = false;
    }
    if (max && vol[r] > 1.5 * mean) hvn.push(r);
    else if (min && vol[r] > 0 && vol[r] < 0.5 * mean) lvn.push(r);
  }
  return { lo, step, vol, total, poc, vaLo, vaHi, hvn, lvn };
}

/** The price at the middle of row `r`. */
export const rowPrice = (p: Profile, r: number) => p.lo + (r + 0.5) * p.step;

/** Bar index ranges [from, to) for one profile per session / week / month (same reset rules as `avwap.ts`). */
export function periods(t: Float64Array, kind: "SESSION" | "WEEK" | "MONTH"): [number, number][] {
  const key = (x: number) =>
    kind === "WEEK" ? Math.floor((x / 86_400 + 3) / 7) : kind === "MONTH" ? new Date(x * 1000).getUTCFullYear() * 12 + new Date(x * 1000).getUTCMonth() : 0;
  const out: [number, number][] = [];
  let start = 0;
  for (let i = 1; i <= t.length; i++) {
    const brk = i === t.length || (kind === "SESSION" ? t[i] - t[i - 1] > 4 * 3600 : key(t[i]) !== key(t[i - 1]));
    if (brk) {
      if (i > start) out.push([start, i]);
      start = i;
    }
  }
  return out;
}
