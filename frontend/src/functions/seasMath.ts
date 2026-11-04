/**
 * SEAS: seasonality tables from daily closes. Pure (no DOM, no network). Dates are the calendar date in the exchange time zone (`opts.tz`, e.g. Australia/Sydney); UTC when no zone is given.
 * Month and ISO-week figures are period returns (last close of the period over the last close of the previous period);
 * weekday and day-of-month figures are close-to-close daily returns assigned to the date of the later bar.
 * A period needs a previous period in the data, so the first (partial) month or week is never counted.
 */

import { civilFromDays, daysFromCivil, localDayNumbers } from "./dayMath";

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

/**
 * Integer calendar math. A "day number" is the count of days since 1970-01-01 (a whole number, so no Date objects are
 * needed per bar). These two functions are the standard "civil from days" / "days from civil" algorithms (H. Hinnant).
 */
/** Monday = 0 .. Sunday = 6 (1970-01-01 was a Thursday, which is 3). */
export { civilFromDays };
export function weekdayMon0(days: number): number {
  return (((days + 3) % 7) + 7) % 7;
}

/** ISO 8601 week of a day number. The Thursday of the week decides which year the week belongs to. */
function isoWeekOfDays(days: number): { year: number; week: number } {
  const thursday = days - weekdayMon0(days) + 3;
  const year = civilFromDays(thursday).y;
  return { year, week: Math.floor((thursday - daysFromCivil(year, 1, 1)) / 7) + 1 };
}

/** ISO 8601 week of the UTC date of an epoch-seconds timestamp. */
export function isoWeek(tSec: number): { year: number; week: number } {
  return isoWeekOfDays(Math.floor(tSec / 86400));
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
function periodReturns(t: Float64Array, c: Float64Array, keyOf: (i: number) => number, infoOf: (i: number) => { bucket: number; year: number }, skipLast: boolean) {
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
    const key = keyOf(i); // a plain number per bar: no object allocated here
    if (key !== curKey) {
      flush();
      if (curKey >= 0) {
        prevKey = curKey;
        prevClose = curClose;
      }
      curKey = key;
      const info = infoOf(i); // bucket and year are only needed once per month/week, not per bar
      curBucket = info.bucket;
      curYear = info.year;
    }
    curClose = c[i];
  }
  void prevKey;
  if (!skipLast) flush();
  return out;
}

export function seasonality(t: Float64Array, c: Float64Array, kind: SeasKind, opts: { excludeOpenPeriodAt?: number; tz?: string | null } = {}): SeasResult {
  const tz = opts.tz;
  const n = Math.min(t.length, c.length);
  const tt = t.subarray(0, n);
  const cc = c.subarray(0, n);
  const openAt = opts.excludeOpenPeriodAt;
  const days = localDayNumbers(tt, tz); // one day number per bar, shared by every kind below
  const dayOf = (sec: number) => localDayNumbers([sec], tz)[0];
  // Group key per bar: months = year*12+month, ISO weeks = year*60+week. Numbers only; bucket/year come from infoOf.
  const monthKeyOfDay = (dn: number) => {
    const { y, m } = civilFromDays(dn);
    return y * 12 + (m - 1);
  };
  const weekKeyOfDay = (dn: number) => {
    const w = isoWeekOfDays(dn);
    return w.year * 60 + w.week;
  };
  const monthInfo = (dn: number) => {
    const { y, m } = civilFromDays(dn);
    return { bucket: m - 1, year: y };
  };
  const weekInfo = (dn: number) => {
    const w = isoWeekOfDays(dn);
    return { bucket: w.week - 1, year: w.year };
  };
  let rows: SeasRow[];
  let obs = 0;
  if (kind === "MONTH" || kind === "WOY") {
    const ofDay = kind === "MONTH" ? monthKeyOfDay : weekKeyOfDay;
    const infoOfDay = kind === "MONTH" ? monthInfo : weekInfo;
    const skipLast = openAt !== undefined && n > 0 && ofDay(dayOf(openAt)) === ofDay(days[n - 1]);
    const pr = periodReturns(tt, cc, (i) => ofDay(days[i]), (i) => infoOfDay(days[i]), skipLast);
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
      const b = kind === "WEEKDAY" ? weekdayMon0(days[i]) : civilFromDays(days[i]).d - 1;
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
    firstYear: n ? civilFromDays(days[0]).y : NaN,
    lastYear: n ? civilFromDays(days[n - 1]).y : NaN,
    obs,
    bars: n,
  };
}
