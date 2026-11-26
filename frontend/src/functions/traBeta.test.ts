import { describe, expect, it } from "vitest";
import { betaViewArgs, datedBars, dayToEpoch, fitLine, nextPeriod, nextRange, parseBetaArgs, parseTraArgs, scatterBox, traViewArgs } from "./traBeta";

describe("TRA and BETA arguments", () => {
  it("reads a TRA list, range and benchmark", () => {
    expect(parseTraArgs(["aapl,msft", "3y", "vs", "qqq"])).toEqual({ symbols: ["AAPL", "MSFT"], vs: "QQQ", range: "3Y", error: null });
    expect(parseTraArgs([], "nvda").symbols).toEqual(["NVDA"]); // no symbol typed: the panel's own security
    expect(parseTraArgs([]).error).toMatch(/USAGE/);
  });
  it("treats a lone W as the period only when a security is already known", () => {
    expect(parseBetaArgs(["AAPL", "W"]).per).toBe("W");
    expect(parseBetaArgs(["W"]).symbol).toBe("W"); // no sticky security: W is the ticker
    expect(parseBetaArgs(["W"], "AAPL").per).toBe("W");
    expect(parseBetaArgs(["AAPL", "WIN=2"]).error).toMatch(/WIN MUST BE/);
  });
  it("round-trips the args a key press writes back into the view", () => {
    const b = parseBetaArgs(betaViewArgs({ vs: "QQQ", range: "5Y", per: "M", win: 26 }), "AAPL");
    expect(b).toMatchObject({ symbol: "AAPL", vs: "QQQ", range: "5Y", per: "M", win: 26, error: null });
    expect(parseTraArgs(traViewArgs({ symbols: ["AAPL", "MSFT"], vs: "^NSEI", range: "YTD" }))).toMatchObject({ symbols: ["AAPL", "MSFT"], vs: "^NSEI", range: "YTD" });
  });
  it("cycles the period and the range", () => {
    expect(nextPeriod("D")).toBe("W");
    expect(nextPeriod("M")).toBe("D");
    expect(nextRange("1M")).toBe("3M");
    expect(nextRange("MAX")).toBe("1M");
  });
});

describe("TRA and BETA chart helpers", () => {
  it("turns dates into epoch seconds and drops bad points instead of filling them", () => {
    expect(dayToEpoch("1970-01-02")).toBe(86400);
    expect(Number.isNaN(dayToEpoch("junk"))).toBe(true);
    const bars = datedBars("X", ["2024-01-01", "bad", "2024-01-03"], [1, 2, NaN]);
    expect(Array.from(bars.c)).toEqual([1]);
    expect(bars.t.length).toBe(1);
  });
  it("keeps zero inside the scatter box and draws the fitted line across it", () => {
    const box = scatterBox([1, 2, 3], [2, 4, 6])!;
    expect(box.xMin).toBeLessThan(0);
    expect(box.yMin).toBeLessThan(0);
    expect(scatterBox([], [])).toBeNull();
    const [a, b] = fitLine(box, 0.5, 2);
    expect(a[1]).toBeCloseTo(0.5 + 2 * box.xMin);
    expect(b[0]).toBe(box.xMax);
  });
});
