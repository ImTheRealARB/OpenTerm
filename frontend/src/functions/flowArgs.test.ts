import { describe, expect, it } from "vitest";
import { clockMin, clockMs, filterText, fmtQty, fmtSigned, parseAmount, parseBigtArgs, parseFootArgs, parseTasArgs } from "./flowArgs";

describe("parseAmount", () => {
  it("reads plain numbers and K / M / B suffixes", () => {
    expect(parseAmount("250")).toBe(250);
    expect(parseAmount("0.5")).toBe(0.5);
    expect(parseAmount("250k")).toBe(250_000);
    expect(parseAmount("1.5M")).toBe(1_500_000);
    expect(parseAmount("2B")).toBe(2e9);
  });
  it("rejects anything else", () => {
    for (const bad of ["", "abc", "-5", "0", "1e3", "5X"]) expect(parseAmount(bad)).toBeNull();
  });
});

describe("TAS / BIGT / FOOT arguments", () => {
  it("TAS: words are the symbol, else the sticky security, else BTCUSDT", () => {
    expect(parseTasArgs(["btc", "usdt"]).sym).toBe("BTCUSDT");
    expect(parseTasArgs([], "eth-usd").sym).toBe("ETH-USD");
    expect(parseTasArgs([]).sym).toBe("BTCUSDT");
  });
  it("BIGT: MIN= coins or USD= amount", () => {
    expect(parseBigtArgs(["ETHUSDT", "MIN=5"])).toEqual({ sym: "ETHUSDT", min: 5 });
    expect(parseBigtArgs(["usd=250k"])).toEqual({ sym: "BTCUSDT", usd: 250_000 });
    expect(parseBigtArgs(["BTCUSDT"])).toEqual({ sym: "BTCUSDT" });
    expect(parseBigtArgs(["MIN=zero"]).error).toMatch(/MIN=/);
  });
  it("FOOT: interval word, bar count (clamped), symbol", () => {
    expect(parseFootArgs(["BTCUSDT", "5m", "40"])).toEqual({ sym: "BTCUSDT", interval: "5M", bars: 40 });
    expect(parseFootArgs([])).toEqual({ sym: "BTCUSDT", interval: "1M", bars: 30 });
    expect(parseFootArgs(["1", "999"]).bars).toBe(120);
    expect(parseFootArgs(["2"]).bars).toBe(3);
  });
});

describe("number and time text", () => {
  it("fmtQty keeps cells short at every size", () => {
    expect(fmtQty(0)).toBe("0");
    expect(fmtQty(0.00036)).toBe("0.0004");
    expect(fmtQty(0.11483)).toBe("0.115");
    expect(fmtQty(12.345)).toBe("12.35");
    expect(fmtQty(234.56)).toBe("234.6");
    expect(fmtQty(12345)).toBe("12.3K");
  });
  it("fmtSigned prefixes a plus on gains only", () => {
    expect(fmtSigned(3.5)).toBe("+3.500");
    expect(fmtSigned(-1.25)).toBe("-1.250");
    expect(fmtSigned(0)).toBe("0");
  });
  it("clocks are UTC", () => {
    expect(clockMs(Date.UTC(2026, 10, 24, 14, 3, 22, 417))).toBe("14:03:22.417");
    expect(clockMin(Date.UTC(2026, 10, 24, 14, 3, 22))).toBe("14:03");
  });
  it("filterText names the unit", () => {
    expect(filterText({ min_qty: 5, usd: null }, "BTC")).toBe("AT LEAST 5 BTC");
    expect(filterText({ min_qty: null, usd: 100000 }, "BTC")).toBe("AT LEAST $100,000");
  });
});
