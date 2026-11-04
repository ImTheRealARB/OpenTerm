import { describe, expect, it } from "vitest";
import { civilFromDays, localDayNumbers } from "./dayMath";

describe("localDayNumbers", () => {
  // Reference: Intl formats the date directly (slow, per bar). The offset table must agree everywhere, DST changes included.
  for (const zone of ["America/New_York", "Australia/Sydney", "Asia/Kolkata", "Europe/London", "Pacific/Auckland"]) {
    it(`matches Intl for ${zone} over 12 years of hourly-ish stamps`, () => {
      const f = new Intl.DateTimeFormat("en-CA", { timeZone: zone, year: "numeric", month: "2-digit", day: "2-digit" });
      const t = new Float64Array(6000);
      let x = Date.UTC(2014, 0, 1) / 1000;
      for (let i = 0; i < t.length; i++) t[i] = x += 3600 * 17 + (i % 5) * 600; // ascending, drifts through every hour of the day
      const days = localDayNumbers(t, zone);
      for (let i = 0; i < t.length; i += 7) {
        const { y, m, d } = civilFromDays(days[i]);
        expect(`${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`).toBe(f.format(new Date(t[i] * 1000)));
      }
    });
  }
  it("falls back to UTC for no zone or an unknown zone", () => {
    const t = [1_700_000_000];
    expect(localDayNumbers(t, null)[0]).toBe(Math.floor(1_700_000_000 / 86400));
    expect(localDayNumbers(t, "Not/AZone")[0]).toBe(Math.floor(1_700_000_000 / 86400));
  });
});
