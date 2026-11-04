/**
 * Exchange-local calendar day numbers for a whole array of bar times, with integer math only.
 * A "day number" is the count of days since 1970-01-01. No Date, string or Map is touched per bar.
 *
 * For a non-UTC zone the only thing that changes the local day is the zone's UTC offset, and that offset is a step
 * function of time (it jumps at daylight-saving changes). So we build, once per call, a small table of the jumps
 * (sorted transition times + the offset after each) by asking Intl at month boundaries and bisecting where the
 * offset changed. Then the bars (sorted by time) walk that table with one moving index.
 */

/** Days since 1970-01-01 of a civil (year, month 1-12, day) date. Integer math ("days from civil", H. Hinnant). */
export function daysFromCivil(y: number, m: number, d: number): number {
  const yy = m <= 2 ? y - 1 : y;
  const era = Math.floor(yy / 400);
  const yoe = yy - era * 400;
  const doy = Math.floor((153 * (m > 2 ? m - 3 : m + 9) + 2) / 5) + d - 1;
  const doe = yoe * 365 + Math.floor(yoe / 4) - Math.floor(yoe / 100) + doy;
  return era * 146097 + doe - 719468;
}

/** Inverse of daysFromCivil: year, month (1-12) and day of a day number. */
export function civilFromDays(days: number): { y: number; m: number; d: number } {
  const z = days + 719468;
  const era = Math.floor(z / 146097);
  const doe = z - era * 146097; // day of the 400-year era, 0..146096
  const yoe = Math.floor((doe - Math.floor(doe / 1460) + Math.floor(doe / 36524) - Math.floor(doe / 146096)) / 365);
  const doy = doe - (365 * yoe + Math.floor(yoe / 4) - Math.floor(yoe / 100)); // day of the year counted from March 1
  const mp = Math.floor((5 * doy + 2) / 153); // month counted from March (0 = March)
  const d = doy - Math.floor((153 * mp + 2) / 5) + 1;
  const m = mp < 10 ? mp + 3 : mp - 9;
  return { y: yoe + era * 400 + (m <= 2 ? 1 : 0), m, d };
}

const UTC_NAMES = new Set(["UTC", "Etc/UTC", "GMT"]);

/** UTC offset (seconds, local minus UTC) of a zone at an instant, read from Intl. Used a few hundred times per call, never per bar. */
function offsetAt(f: Intl.DateTimeFormat, tSec: number): number {
  let y = 0, mo = 0, d = 0, h = 0, mi = 0, s = 0;
  for (const p of f.formatToParts(new Date(tSec * 1000))) {
    const v = +p.value;
    if (p.type === "year") y = v;
    else if (p.type === "month") mo = v;
    else if (p.type === "day") d = v;
    else if (p.type === "hour") h = v % 24; // some engines print midnight as 24
    else if (p.type === "minute") mi = v;
    else if (p.type === "second") s = v;
  }
  return daysFromCivil(y, mo, d) * 86400 + h * 3600 + mi * 60 + s - Math.floor(tSec);
}

/** Offset table for [lo, hi] (epoch seconds): tr[j] = start of segment j (first is -Infinity), off[j] = its offset. */
function offsetTable(zone: string, lo: number, hi: number): { tr: Float64Array; off: Int32Array } | null {
  let f: Intl.DateTimeFormat;
  try {
    f = new Intl.DateTimeFormat("en-US", { timeZone: zone, hourCycle: "h23", year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "numeric", second: "numeric" });
  } catch {
    return null; // unknown zone: caller falls back to UTC
  }
  const trs: number[] = [-Infinity];
  const offs: number[] = [offsetAt(f, lo)];
  // Probe about once a month (30 days is shorter than any gap between two offset changes), bisect when the offset moved.
  const STEP = 30 * 86400;
  let prevT = lo;
  let prevOff = offs[0];
  for (let t = lo + STEP; ; t += STEP) {
    const tt = Math.min(t, hi);
    const o = offsetAt(f, tt);
    if (o !== prevOff) {
      let a = prevT; // offset == prevOff at a
      let b = tt; // offset == o at b
      while (b - a > 1) {
        const mid = Math.floor((a + b) / 2);
        if (offsetAt(f, mid) === prevOff) a = mid;
        else b = mid;
      }
      trs.push(b);
      offs.push(o);
      prevOff = o;
    }
    prevT = tt;
    if (tt >= hi) break;
  }
  return { tr: Float64Array.from(trs), off: Int32Array.from(offs) };
}

/** Exchange-local day number of each time (epoch seconds). `tz` empty or UTC: floor(t / 86400). Unknown zone: UTC. */
export function localDayNumbers(t: ArrayLike<number>, tz?: string | null): Float64Array {
  const n = t.length;
  const out = new Float64Array(n);
  let table: { tr: Float64Array; off: Int32Array } | null = null;
  if (tz && !UTC_NAMES.has(tz) && n) {
    let lo = Infinity;
    let hi = -Infinity;
    for (let i = 0; i < n; i++) {
      if (t[i] < lo) lo = t[i];
      if (t[i] > hi) hi = t[i];
    }
    if (Number.isFinite(lo)) table = offsetTable(tz, Math.floor(lo), Math.ceil(hi));
  }
  if (!table) {
    for (let i = 0; i < n; i++) out[i] = Math.floor(t[i] / 86400);
    return out;
  }
  const { tr, off } = table;
  let j = 0; // current segment; bars arrive in time order, so it only moves forward
  for (let i = 0; i < n; i++) {
    const x = t[i];
    if (x < tr[j]) j = 0; // out-of-order bar: restart the walk
    while (j + 1 < tr.length && x >= tr[j + 1]) j++;
    out[i] = Math.floor((x + off[j]) / 86400);
  }
  return out;
}
