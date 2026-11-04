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

/**
 * Packed calendar date of a day number: year * 512 + month * 32 + day (month 1..12 fits in 4 bits, day 1..31 in 5 bits).
 * Same "civil from days" algorithm as dayMath.civilFromDays, but it returns ONE number instead of a {y, m, d} object,
 * so the per-bar loops below allocate nothing (data-oriented rule: pack small fields into an integer).
 */
function civilPacked(days: number): number {
  const z = days + 719468;
  const era = Math.floor(z / 146097);
  const doe = z - era * 146097;
  const yoe = Math.floor((doe - Math.floor(doe / 1460) + Math.floor(doe / 36524) - Math.floor(doe / 146096)) / 365);
  const doy = doe - (365 * yoe + Math.floor(yoe / 4) - Math.floor(yoe / 100));
  const mp = Math.floor((5 * doy + 2) / 153);
  const d = doy - Math.floor((153 * mp + 2) / 5) + 1;
  const m = mp < 10 ? mp + 3 : mp - 9;
  return (yoe + era * 400 + (m <= 2 ? 1 : 0)) * 512 + m * 32 + d;
}
const pYear = (p: number) => Math.floor(p / 512);
const pMonth = (p: number) => (p >> 5) & 15; // 1..12 (years here are positive, so the low bits are safe to mask)
const pDay = (p: number) => p & 31; // 1..31

/** Packed ISO 8601 week of a day number: isoYear * 64 + week. The Thursday of the week decides the year. */
function isoWeekPacked(days: number): number {
  const thursday = days - weekdayMon0(days) + 3;
  const year = pYear(civilPacked(thursday));
  return year * 64 + Math.floor((thursday - daysFromCivil(year, 1, 1)) / 7) + 1;
}

/** ISO 8601 week of the UTC date of an epoch-seconds timestamp. */
export function isoWeek(tSec: number): { year: number; week: number } {
  const w = isoWeekPacked(Math.floor(tSec / 86400));
  return { year: Math.floor(w / 64), week: w & 63 };
}

/** Summary of one bucket. `v` is a scratch slice owned by this call, so it is sorted in place (typed-array sort is numeric). */
function row(label: string, v: Float64Array): SeasRow {
  const n = v.length;
  if (!n) return { label, n: 0, avg: NaN, median: NaN, hit: NaN, min: NaN, max: NaN };
  let sum = 0;
  let hit = 0;
  for (let i = 0; i < n; i++) {
    sum += v[i];
    if (v[i] > 0) hit++;
  }
  v.sort();
  const mid = n % 2 ? v[(n - 1) / 2] : (v[n / 2 - 1] + v[n / 2]) / 2;
  return { label, n, avg: sum / n, median: mid, hit: hit / n, min: v[0], max: v[n - 1] };
}

/**
 * Group (bucket, return) pairs held in two parallel arrays (struct of arrays) into one Float64Array with a counting sort:
 * count per bucket, turn counts into start offsets, then drop each return into its slot. No per-bucket arrays, no push().
 */
function bucketRows(bk: Uint8Array, ret: Float64Array, m: number, size: number, label: (i: number) => string): SeasRow[] {
  const start = new Int32Array(size + 1);
  for (let i = 0; i < m; i++) start[bk[i] + 1]++;
  for (let b = 0; b < size; b++) start[b + 1] += start[b];
  const fill = start.slice(0, size);
  const flat = new Float64Array(m);
  for (let i = 0; i < m; i++) flat[fill[bk[i]]++] = ret[i];
  const rows: SeasRow[] = new Array(size);
  for (let b = 0; b < size; b++) rows[b] = row(label(b), flat.subarray(start[b], start[b + 1]));
  return rows;
}

const monthLabel = (i: number) => MONTHS[i];
const weekdayLabel = (i: number) => WEEKDAYS[i];
const numberLabel = (i: number) => String(i + 1);

export function seasonality(t: Float64Array, c: Float64Array, kind: SeasKind, opts: { excludeOpenPeriodAt?: number; tz?: string | null } = {}): SeasResult {
  const tz = opts.tz;
  const n = Math.min(t.length, c.length);
  const tt = t.subarray(0, n);
  const cc = c.subarray(0, n);
  const openAt = opts.excludeOpenPeriodAt;
  const days = localDayNumbers(tt, tz); // one day number per bar, shared by every kind below
  // Parallel output columns (struct of arrays): bucket index and return of each observation.
  const bk = new Uint8Array(n);
  const ret = new Float64Array(n);
  let m = 0;
  let rows: SeasRow[];
  if (kind === "MONTH" || kind === "WOY") {
    // Period key per bar is a plain integer: months = year*12 + month-1, ISO weeks = the packed week (year*64 + week).
    const isMonth = kind === "MONTH";
    const keyOf = (dn: number) => {
      if (isMonth) {
        const p = civilPacked(dn);
        return pYear(p) * 12 + pMonth(p) - 1;
      }
      return isoWeekPacked(dn);
    };
    const bucketOfKey = (k: number) => (isMonth ? k % 12 : (k & 63) - 1);
    const skipLast = openAt !== undefined && n > 0 && keyOf(localDayNumbers([openAt], tz)[0]) === keyOf(days[n - 1]);
    // One pass: when the key changes, the previous period is complete; its return is its last close over the period before.
    let prevClose = NaN;
    let curKey = -1;
    let curClose = NaN;
    for (let i = 0; i < n; i++) {
      if (!Number.isFinite(cc[i])) continue;
      const key = keyOf(days[i]);
      if (key !== curKey) {
        if (curKey >= 0 && Number.isFinite(prevClose) && prevClose !== 0) {
          bk[m] = bucketOfKey(curKey);
          ret[m++] = curClose / prevClose - 1;
        }
        if (curKey >= 0) prevClose = curClose;
        curKey = key;
      }
      curClose = cc[i];
    }
    if (!skipLast && curKey >= 0 && Number.isFinite(prevClose) && prevClose !== 0) {
      bk[m] = bucketOfKey(curKey);
      ret[m++] = curClose / prevClose - 1;
    }
    rows = bucketRows(bk, ret, m, isMonth ? 12 : 53, isMonth ? monthLabel : numberLabel);
  } else {
    // Daily close-to-close returns, bucketed by the later bar's weekday (Mon..Fri) or day of month.
    const isWeekday = kind === "WEEKDAY";
    const size = isWeekday ? 5 : 31;
    for (let i = 1; i < n; i++) {
      if (!Number.isFinite(cc[i]) || !Number.isFinite(cc[i - 1]) || cc[i - 1] === 0) continue;
      const b = isWeekday ? weekdayMon0(days[i]) : pDay(civilPacked(days[i])) - 1;
      if (b < size) {
        bk[m] = b;
        ret[m++] = cc[i] / cc[i - 1] - 1;
      }
    }
    rows = bucketRows(bk, ret, m, size, isWeekday ? weekdayLabel : numberLabel);
  }
  return {
    kind,
    rows,
    firstYear: n ? pYear(civilPacked(days[0])) : NaN,
    lastYear: n ? pYear(civilPacked(days[n - 1])) : NaN,
    obs: m,
    bars: n,
  };
}
