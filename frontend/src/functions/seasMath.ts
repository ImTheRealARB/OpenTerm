/**
 * SEAS: seasonality tables from daily closes. Pure (no DOM, no network). Dates are the UTC date of the bar timestamp.
 * Month and ISO-week figures are period returns (last close of the period over the last close of the previous period);
 * weekday and day-of-month figures are close-to-close daily returns assigned to the date of the later bar.
 * A period needs a previous period in the data, so the first (partial) month or week is never counted.
 */

export type SeasKind = "MONTH" | "WEEKDAY" | "DOM" | "WOY";
export const SEAS_KINDS: SeasKind[] = ["MONTH", "WEEKDAY", "DOM", "WOY"];

export interface SeasRow {
  label: string;
  n: number;
  avg: number;
  median: number;
  /** Share of observations with a return above zero (0..1). */
  hit: number;
  min: number;
  max: number;
}

export interface SeasResult {
  kind: SeasKind;
  rows: SeasRow[];
  firstYear: number;
  lastYear: number;
  /** Observations used across all rows. */
  obs: number;
  bars: number;
}

const MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
const WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI"];

export function parseSeasArgs(args: string[]): { kind: SeasKind } {
  for (const a of args) {
    const u = a.toUpperCase();
    if ((SEAS_KINDS as string[]).includes(u)) return { kind: u as SeasKind };
    if (u === "WD" || u === "DAY") return { kind: "WEEKDAY" };
  }
  return { kind: "MONTH" };
}

/** ISO 8601 week of the UTC date of an epoch-seconds timestamp. */
export function isoWeek(tSec: number): { year: number; week: number } {
  const src = new Date(tSec * 1000);
  const d = new Date(Date.UTC(src.getUTCFullYear(), src.getUTCMonth(), src.getUTCDate()));
  const dn = (d.getUTCDay() + 6) % 7;
  d.setUTCDate(d.getUTCDate() - dn + 3); // the Thursday of this ISO week decides the year
  const jan4 = new Date(Date.UTC(d.getUTCFullYear(), 0, 4));
  const week = 1 + Math.round(((d.getTime() - jan4.getTime()) / 86400000 - 3 + ((jan4.getUTCDay() + 6) % 7)) / 7);
  return { year: d.getUTCFullYear(), week };
}

function row(label: string, rets: number[]): SeasRow {
  const n = rets.length;
  if (!n) return { label, n: 0, avg: NaN, median: NaN, hit: NaN, min: NaN, max: NaN };
  const s = [...rets].sort((a, b) => a - b);
  const mid = n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2;
  let sum = 0;
  let hit = 0;
  for (const r of rets) {
    sum += r;
    if (r > 0) hit++;
  }
  return { label, n, avg: sum / n, median: mid, hit: hit / n, min: s[0], max: s[n - 1] };
}

/** Period returns: groups bars by `keyOf`, takes each group's last close, returns {bucket, ret} for groups with a previous group. */
function periodReturns(t: Float64Array, c: Float64Array, keyOf: (tSec: number) => { key: number; bucket: number; year: number }, skipLast: boolean) {
  const out: { bucket: number; ret: number; year: number }[] = [];
  let prevKey = -1;
  let prevClose = NaN;
  let curKey = -1;
  let curClose = NaN;
  let curBucket = 0;
  let curYear = 0;
  const flush = () => {
    if (curKey >= 0 && Number.isFinite(prevClose) && Number.isFinite(curClose) && prevClose !== 0) out.push({ bucket: curBucket, ret: curClose / prevClose - 1, year: curYear });
  };
  for (let i = 0; i < t.length; i++) {
    if (!Number.isFinite(c[i])) continue;
    const k = keyOf(t[i]);
    if (k.key !== curKey) {
      flush();
      if (curKey >= 0) {
        prevKey = curKey;
        prevClose = curClose;
      }
      curKey = k.key;
      curBucket = k.bucket;
      curYear = k.year;
    }
    curClose = c[i];
  }
  void prevKey;
  if (!skipLast) flush();
  return out;
}

export function seasonality(t: Float64Array, c: Float64Array, kind: SeasKind, opts: { excludeOpenPeriodAt?: number } = {}): SeasResult {
  const n = Math.min(t.length, c.length);
  const tt = t.subarray(0, n);
  const cc = c.subarray(0, n);
  const lastT = n ? tt[n - 1] : NaN;
  const openAt = opts.excludeOpenPeriodAt;
  const monthKey = (s: number) => {
    const d = new Date(s * 1000);
    return { key: d.getUTCFullYear() * 12 + d.getUTCMonth(), bucket: d.getUTCMonth(), year: d.getUTCFullYear() };
  };
  const weekKey = (s: number) => {
    const w = isoWeek(s);
    return { key: w.year * 60 + w.week, bucket: w.week - 1, year: w.year };
  };
  let rows: SeasRow[];
  let obs = 0;
  if (kind === "MONTH" || kind === "WOY") {
    const keyOf = kind === "MONTH" ? monthKey : weekKey;
    const skipLast = openAt !== undefined && n > 0 && keyOf(openAt).key === keyOf(lastT).key;
    const pr = periodReturns(tt, cc, keyOf, skipLast);
    const size = kind === "MONTH" ? 12 : 53;
    const buckets: number[][] = Array.from({ length: size }, () => []);
    for (const p of pr) if (p.bucket < size) buckets[p.bucket].push(p.ret);
    rows = buckets.map((b, i) => row(kind === "MONTH" ? MONTHS[i] : String(i + 1), b));
    obs = pr.length;
  } else {
    const size = kind === "WEEKDAY" ? 5 : 31;
    const buckets: number[][] = Array.from({ length: size }, () => []);
    for (let i = 1; i < n; i++) {
      if (!Number.isFinite(cc[i]) || !Number.isFinite(cc[i - 1]) || cc[i - 1] === 0) continue;
      const d = new Date(tt[i] * 1000);
      const b = kind === "WEEKDAY" ? (d.getUTCDay() + 6) % 7 : d.getUTCDate() - 1;
      if (b < size) {
        buckets[b].push(cc[i] / cc[i - 1] - 1);
        obs++;
      }
    }
    rows = buckets.map((b, i) => row(kind === "WEEKDAY" ? WEEKDAYS[i] : String(i + 1), b));
  }
  return {
    kind,
    rows,
    firstYear: n ? new Date(tt[0] * 1000).getUTCFullYear() : NaN,
    lastYear: n ? new Date(lastT * 1000).getUTCFullYear() : NaN,
    obs,
    bars: n,
  };
}
