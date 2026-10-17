import { describe, expect, it } from "vitest";
import { parseCommand } from "./parser";
import { fuzzyRank, fuzzyScore } from "./fuzzy";

const FNS = new Set(["GP", "DES", "N", "WEI", "HELP", "FRED", "Q"]);
const isFn = (c: string) => FNS.has(c);
const p = (s: string) => parseCommand(s, isFn);

describe("parseCommand", () => {
  it("security + function", () => {
    expect(p("aapl gp")).toMatchObject({ ok: true, security: { symbol: "AAPL" }, fn: "GP", args: [] });
  });
  it("function only with args", () => {
    expect(p("HELP GP")).toMatchObject({ ok: true, fn: "HELP", args: ["GP"] }); expect(p("HELP GP")).not.toHaveProperty("security");
    expect(p("FRED GDP")).toMatchObject({ ok: true, fn: "FRED", args: ["GDP"] });
  });
  it("args after function", () => {
    expect(p("AAPL GP 1Y D")).toMatchObject({ fn: "GP", args: ["1Y", "D"] });
    expect(p("AAPL GP vs SPY")).toMatchObject({ fn: "GP", args: ["vs", "SPY"] });
  });
  it("explicit suffix symbols are untouched", () => {
    expect(p("RELIANCE.NS DES")).toMatchObject({ security: { symbol: "RELIANCE.NS" }, fn: "DES" });
    expect(p("BTC-USD GP")).toMatchObject({ security: { symbol: "BTC-USD" } });
  });
  it("market token maps to suffix", () => {
    expect(p("RELIANCE IN GP")).toMatchObject({ security: { symbol: "RELIANCE.NS", market: "IN" }, fn: "GP" });
    expect(p("AAPL US EQUITY GP")).toMatchObject({ security: { symbol: "AAPL", market: "US" }, fn: "GP" });
  });
  it("panel target prefix", () => {
    expect(p("2: MSFT DES")).toMatchObject({ ok: true, target: 2, security: { symbol: "MSFT" }, fn: "DES" });
    expect(p("3:GP")).toMatchObject({ ok: true, target: 3, fn: "GP" });
    expect(p("2:")).toMatchObject({ ok: false });
  });
  it("security alone has no function", () => {
    expect(p("EURUSD")).toMatchObject({ ok: true, security: { symbol: "EURUSD" } }); expect(p("EURUSD")).not.toHaveProperty("fn");
  });
  it("leading function code wins over same-named ticker", () => {
    expect(p("N")).toMatchObject({ ok: true, fn: "N" }); expect(p("N")).not.toHaveProperty("security");
    expect(p("AAPL N")).toMatchObject({ fn: "N", security: { symbol: "AAPL" } });
  });
  it("errors", () => {
    expect(p("   ")).toMatchObject({ ok: false, error: "EMPTY COMMAND" });
    expect(p("AAPL XYZ")).toMatchObject({ ok: false, error: "UNKNOWN FUNCTION: XYZ" });
    expect(p("$$$ GP")).toMatchObject({ ok: false });
  });
});

describe("fuzzy", () => {
  it("ranks exact and prefix first", () => {
    expect(fuzzyScore("gp", "GP")).toBeGreaterThan(fuzzyScore("gp", "GPX"));
    expect(fuzzyScore("xz", "GP")).toBe(-1);
    expect(fuzzyRank("de", ["HELP", "DES", "MODE"], (s) => s, 2)).toEqual(["DES", "MODE"]);
  });
});
