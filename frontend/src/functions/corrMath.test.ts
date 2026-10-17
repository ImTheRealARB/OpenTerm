import { describe, expect, it } from "vitest";
import { alignCloses, correlationMatrix, corrBand, dayKey, logReturns, parseCorrArgs, pearson } from "./corrMath";
import { histArgs, histRows, pctChange, periodReturn } from "./returns";

const D = 86400;
const T0 = Date.UTC(2026, 0, 5, 14, 30) / 1000; // Monday 2026-01-05 14:30 UTC (09:30 New York)
const days = (n: number) => Array.from({ length: n }, (_, i) => T0 + i * D);

describe("correlation math", () => {
  it("pearson matches a hand-computed value", () => {
    // mean x 2.5, mean y 3.75; Sxy 3.5, Sxx 5, Syy 4.75 -> 3.5 / sqrt(23.75) = 0.718185...
    expect(pearson([1, 2, 3, 4], [2, 4, 5, 4])).toBeCloseTo(0.718185, 6);
    expect(pearson([1, 2, 3], [3, 2, 1])).toBeCloseTo(-1, 12);
    expect(pearson([1, 1, 1], [1, 2, 3])).toBeNaN(); // constant side
    expect(pearson([1], [1])).toBeNaN();
  });

  it("log returns", () => {
    const r = logReturns([100, 110, 99]);
    expect(r[0]).toBeCloseTo(Math.log(1.1), 12);
    expect(r[1]).toBeCloseTo(Math.log(0.9), 12);
    expect(logReturns([5])).toEqual([]);
  });

  it("identical moves correlate +1, mirrored moves -1", () => {
    const t = days(4);
    const up = { symbol: "A", t, c: [100, 110, 99, 108.9] }; // +10%, -10%, +10%
    const same = { symbol: "B", t, c: [50, 55, 49.5, 54.45] };
    const mirror = { symbol: "C", t, c: [100, 100 / 1.1, 100 / 0.99, 100 / 1.089] }; // returns negated
    const r = correlationMatrix([up, same, mirror]);
    expect(r.overlap).toBe(4);
    expect(r.returns).toBe(3);
    expect(r.matrix[0][0]).toBe(1);
    expect(r.matrix[0][1]).toBeCloseTo(1, 12);
    expect(r.matrix[0][2]).toBeCloseTo(-1, 12);
    expect(r.matrix[2][0]).toBe(r.matrix[0][2]); // symmetric
  });

  it("aligns by date, dropping days any symbol is missing", () => {
    const t = days(5);
    const a = { symbol: "A", t, c: [10, 11, 12, 13, 14] };
    const b = { symbol: "B", t: [t[0], t[2], t[3], t[4]], c: [20, 22, null, 30] }; // no day 2, null on day 4
    const al = alignCloses([a, b]);
    expect(al.dates).toEqual(["2026-01-05", "2026-01-07", "2026-01-09"]);
    expect(al.closes).toEqual([
      [10, 12, 14],
      [20, 22, 30],
    ]);
    const r = correlationMatrix([a, b]);
    expect(r.overlap).toBe(3);
    expect(r.first).toBe("2026-01-05");
    expect(r.last).toBe("2026-01-09");
  });

  it("dates bars in the exchange's time zone", () => {
    const t = Date.UTC(2026, 9, 15, 21, 0) / 1000; // 21:00 UTC = 10:00 next day in Auckland (NZDT)
    expect(dayKey(t, "Pacific/Auckland")).toBe("2026-10-16");
    expect(dayKey(t, "America/New_York")).toBe("2026-10-15");
    expect(dayKey(t, null)).toBe("2026-10-15");
    expect(dayKey(t, "Not/AZone")).toBe("2026-10-15");
  });

  it("bands carry sign and strength in discrete steps", () => {
    expect([0.95, 0.5, 0.25, 0.1, -0.1, -0.3, -0.45, -0.8, NaN].map(corrBand)).toEqual([
      "p3", "p2", "p1", "z", "z", "m1", "m2", "m3", "",
    ]);
  });

  it("20 symbols x 5 years stays cheap on the main thread", () => {
    const n = 1260;
    const t = days(n);
    let seed = 7;
    const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647 - 0.5;
    const series = Array.from({ length: 20 }, (_, k) => {
      let p = 100;
      return { symbol: `S${k}`, t, c: t.map(() => (p *= 1 + rnd() / 25)) };
    });
    const t0 = performance.now();
    const r = correlationMatrix(series);
    const ms = performance.now() - t0;
    console.log(`correlationMatrix 20 x ${n}: ${ms.toFixed(1)} ms`);
    expect(r.overlap).toBe(n);
    expect(ms).toBeLessThan(100);
  });
});

describe("returns", () => {
  it("percent change", () => {
    expect(pctChange(100, 110)).toBeCloseTo(10, 12);
    expect(pctChange(0, 1)).toBeNull();
    expect(pctChange(null, 1)).toBeNull();
  });

  it("period return uses the last bar at or before the cutoff", () => {
    const t = days(40); // 40 daily bars
    const c = t.map((_, i) => 100 + i); // 100..139
    // 30 days back from the last bar (index 39) is index 9 (close 109): 139/109 - 1.
    expect(periodReturn({ t, c }, 30)).toBeCloseTo((139 / 109 - 1) * 100, 10);
    expect(periodReturn({ t, c }, 39)).toBeCloseTo(39, 10); // exactly the first bar
    expect(periodReturn({ t, c }, 60)).toBeNull(); // history too short
    // Adjusted closes win when present.
    expect(periodReturn({ t, c, adj: c.map((x) => x * 2) }, 30)).toBeCloseTo((139 / 109 - 1) * 100, 10);
    expect(periodReturn({ t, c: c.map(() => null) }, 5)).toBeNull();
  });

  it("HIST rows are newest first with change vs the previous bar", () => {
    const t = days(3);
    const rows = histRows({ t, o: [1, 2, 3], h: [2, 3, 4], l: [0.5, 1.5, 2.5], c: [10, null, 12], v: [100, 200, 300], adj: [9, null, 11] });
    expect(rows.map((r) => r.close)).toEqual([12, 10]); // the null-close bar is dropped
    expect(rows[0].changePct).toBeCloseTo(20, 12);
    expect(rows[0].adj).toBe(11);
    expect(rows[1].changePct).toBeNull();
  });

  it("HIST args", () => {
    expect(histArgs([])).toEqual({ range: "1Y", interval: "D", bad: [] });
    expect(histArgs(["w", "5y"])).toEqual({ range: "5Y", interval: "W", bad: [] });
    expect(histArgs(["MONTHLY", "MAX", "zz"])).toEqual({ range: "MAX", interval: "MO", bad: ["ZZ"] });
  });
});

describe("parseCorrArgs", () => {
  it("takes symbols and an optional range in any order", () => {
    expect(parseCorrArgs(["aapl", "5y", "msft,nvda", "AAPL"])).toEqual({ symbols: ["AAPL", "MSFT", "NVDA"], range: "5Y", error: null });
    expect(parseCorrArgs(["spy", "qqq"]).range).toBe("1Y");
  });
  it("needs two symbols and at most twenty", () => {
    expect(parseCorrArgs(["aapl"]).error).toContain("USAGE");
    expect(parseCorrArgs(Array.from({ length: 21 }, (_, i) => `S${i}`)).error).toContain("AT MOST 20");
  });
});
