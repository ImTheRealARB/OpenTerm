import { describe, expect, it } from "vitest";
import { coneVertices, weekdaysBetween } from "./cone";

describe("cone", () => {
  it("counts weekdays and places expiries past the last daily bar", () => {
    const fri = Date.UTC(2026, 10, 20) / 1000; // Friday 2026-11-20
    expect(weekdaysBetween(fri, fri + 7 * 86400)).toBe(5);
    const t = [fri - 86400, fri];
    const v = coneVertices([{ time: fri + 7 * 86400, lo1: 90, hi1: 110, lo2: 80, hi2: 120 }, { time: fri - 1, lo1: 1, hi1: 1, lo2: 1, hi2: 1 }], t, 100);
    expect(v).toEqual([{ x: 1, lo1: 100, hi1: 100, lo2: 100, hi2: 100 }, { x: 6, lo1: 90, hi1: 110, lo2: 80, hi2: 120 }]);
  });
});
