import { describe, expect, it } from "vitest";
import { niceStep, parseTpoArgs, tpoDay } from "./tpoMath";

describe("TPO profile (Phase 23)", () => {
  it("letters each bracket over its range and finds POC, IB, singles and a poor high", () => {
    // Three 30-minute brackets of 15-minute bars, prices on a 1.0 grid.
    const t = [0, 900, 1800, 2700, 3600];
    const h = [12, 13, 13, 13, 15];
    const l = [10, 11, 12, 12, 13];
    const d = tpoDay("2026-01-02", t, h, l, 1800, 1)!;
    expect(d.brackets).toBe(3);
    // rows 10..15: A covers 10-13, B 12-13, C 13-15
    expect(d.rows).toEqual(["A", "A", "AB", "ABC", "C", "C"]);
    expect(d.poc).toBe(3); // price 13, three letters
    expect([d.ibLo, d.ibHi]).toEqual([10, 13]);
    expect(d.singles).toEqual([1, 4]);
    expect(d.poorHigh).toBe(false);
    expect(d.poorLow).toBe(false);
  });

  it("picks readable row heights", () => {
    expect(niceStep(37, 40)).toBe(1);
    expect(niceStep(150, 40)).toBe(5);
    expect(niceStep(0.3, 40)).toBeCloseTo(0.01);
  });
});

describe("TPO args", () => {
  it("reads days, bracket and an optional symbol", () => {
    expect(parseTpoArgs(["10", "BRACKET=15"], "aapl")).toEqual({ symbol: "AAPL", days: 10, bracket: 15, error: null });
    expect(parseTpoArgs(["MSFT"]).symbol).toBe("MSFT");
    expect(parseTpoArgs(["BRACKET=7"], "AAPL").error).toMatch(/MULTIPLE OF 5/);
    expect(parseTpoArgs([]).error).toMatch(/USAGE/);
  });
});
