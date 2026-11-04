import { describe, expect, it } from "vitest";
import { isoWeek, parseSeasArgs, seasonality } from "./seasMath";

/** Business days 2019-01-01 .. 2023-12-31 (UTC noon), with `bump(date)` giving the multiplier applied on that day. */
function series(bump: (d: Date) => number) {
  const t: number[] = [];
  const c: number[] = [];
  let px = 100;
  for (let ms = Date.UTC(2019, 0, 1, 12); ms <= Date.UTC(2023, 11, 31, 12); ms += 86400000) {
    const d = new Date(ms);
    const wd = d.getUTCDay();
    if (wd === 0 || wd === 6) continue;
    px *= bump(d);
    t.push(ms / 1000);
    c.push(px);
  }
  return { t: Float64Array.from(t), c: Float64Array.from(c) };
}
const weekdaysIn = (y: number, m: number) => {
  let n = 0;
  for (let d = new Date(Date.UTC(y, m, 1)); d.getUTCMonth() === m; d = new Date(d.getTime() + 86400000)) if (d.getUTCDay() % 6 !== 0) n++;
  return n;
};

describe("seasonality", () => {
  it("monthly: a January-only drift shows up in JAN and nowhere else; the partial first month is skipped", () => {
    const { t, c } = series((d) => (d.getUTCMonth() === 0 ? 1.01 : 1));
    const r = seasonality(t, c, "MONTH");
    expect(r.rows.map((x) => x.label)).toEqual(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]);
    const jan = r.rows[0];
    expect(jan.n).toBe(4);
    const want = [2020, 2021, 2022, 2023].map((y) => 1.01 ** weekdaysIn(y, 0) - 1);
    expect(jan.avg).toBeCloseTo(want.reduce((a, b) => a + b) / 4, 10);
    expect(jan.hit).toBe(1);
    expect(jan.min).toBeCloseTo(Math.min(...want), 10);
    expect(jan.max).toBeCloseTo(Math.max(...want), 10);
    expect(r.rows[1].n).toBe(5);
    expect(r.rows[1].avg).toBe(0);
    expect(r.rows[1].hit).toBe(0);
    expect([r.firstYear, r.lastYear]).toEqual([2019, 2023]);
  });

  it("can leave out the month still in progress", () => {
    const { t, c } = series(() => 1.001);
    const all = seasonality(t, c, "MONTH");
    const closed = seasonality(t, c, "MONTH", { excludeOpenPeriodAt: t[t.length - 1] });
    expect(all.rows[11].n).toBe(5);
    expect(closed.rows[11].n).toBe(4);
  });

  it("weekday: a Wednesday-only move", () => {
    const { t, c } = series((d) => (d.getUTCDay() === 3 ? 1.01 : 1));
    const r = seasonality(t, c, "WEEKDAY");
    expect(r.rows.map((x) => x.label)).toEqual(["MON", "TUE", "WED", "THU", "FRI"]);
    expect(r.rows[2].avg).toBeCloseTo(0.01, 10);
    expect(r.rows[2].hit).toBe(1);
    expect(r.rows[2].n).toBeGreaterThan(200);
    expect(r.rows[0].avg).toBe(0);
  });

  it("day of month: only the 15th moves", () => {
    const { t, c } = series((d) => (d.getUTCDate() === 15 ? 1.02 : 1));
    const r = seasonality(t, c, "DOM");
    expect(r.rows).toHaveLength(31);
    expect(r.rows[14].label).toBe("15");
    expect(r.rows[14].avg).toBeCloseTo(0.02, 10);
    expect(r.rows[15].avg).toBe(0);
  });

  it("week of year: ISO week 10 only", () => {
    const { t, c } = series((d) => (isoWeek(d.getTime() / 1000).week === 10 && d.getUTCDay() === 1 ? 1.05 : 1));
    const r = seasonality(t, c, "WOY");
    expect(r.rows[9].label).toBe("10");
    expect(r.rows[9].avg).toBeCloseTo(0.05, 10);
    expect(r.rows[9].n).toBeGreaterThanOrEqual(4);
    expect(r.rows[10].avg).toBe(0);
  });

  it("isoWeek follows ISO 8601 around the new year", () => {
    const s = (y: number, m: number, d: number) => Date.UTC(y, m - 1, d, 12) / 1000;
    expect(isoWeek(s(2021, 1, 3))).toEqual({ year: 2020, week: 53 });
    expect(isoWeek(s(2021, 1, 4))).toEqual({ year: 2021, week: 1 });
    expect(isoWeek(s(2019, 12, 30))).toEqual({ year: 2020, week: 1 });
    expect(isoWeek(s(2023, 3, 8))).toEqual({ year: 2023, week: 10 });
  });

  it("too little data gives empty rows, not an error", () => {
    const r = seasonality(Float64Array.from([1e9]), Float64Array.from([10]), "MONTH");
    expect(r.rows).toHaveLength(12);
    expect(r.rows.every((x) => x.n === 0 && Number.isNaN(x.avg))).toBe(true);
  });

  it("args: kind word, default MONTH", () => {
    expect(parseSeasArgs([])).toEqual({ kind: "MONTH" });
    expect(parseSeasArgs(["weekday"])).toEqual({ kind: "WEEKDAY" });
    expect(parseSeasArgs(["DOM"])).toEqual({ kind: "DOM" });
    expect(parseSeasArgs(["WOY"])).toEqual({ kind: "WOY" });
  });
});

describe("seasonality exchange time zone (audit 2026-11-04 #1)", () => {
  it("files Sydney 23:00 UTC bars under the next local day", () => {
    // Sydney opens 10:00 AEDT = 23:00 UTC the day before: these 5 bars are really Mon..Fri 15-19 Jan 2024 (UTC says Sun..Thu).
    const base = Date.UTC(2024, 0, 14, 23) / 1000;
    const t = Float64Array.from({ length: 5 }, (_, i) => base + i * 86400);
    const c = Float64Array.from([100, 101, 102, 103, 104]);
    // the first bar has no previous close, so Tue..Fri each get one return
    expect(seasonality(t, c, "WEEKDAY", { tz: "Australia/Sydney" }).rows.map((x) => x.n)).toEqual([0, 1, 1, 1, 1]);
    // without a zone the UTC date is used (documented fallback): everything shifts one day early
    expect(seasonality(t, c, "WEEKDAY").rows.map((x) => x.n)).toEqual([1, 1, 1, 1, 0]);
  });
});
