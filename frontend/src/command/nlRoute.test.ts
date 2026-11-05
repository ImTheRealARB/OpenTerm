import { describe, expect, it } from "vitest";
import type { UniverseEntry } from "../gui/companySearch";
import type { NlContext } from "./natural";
import { routeNatural } from "./nlRoute";

const U = (symbol: string, name: string, mcap: number | null): UniverseEntry => ({ symbol, name, mcap });
const UNI: UniverseEntry[] = [
  U("AAPL", "Apple Inc. Common Stock", 3e12),
  U("APLE", "Apple Hospitality REIT, Inc. Common Shares", 3e9),
  U("MSFT", "Microsoft Corporation Common Stock", 3.1e12),
  U("TSLA", "Tesla, Inc. Common Stock", 8e11),
  U("F", "Ford Motor Company Common Stock", 4e10),
  U("GOOGL", "Alphabet Inc. Class A Common Stock", 2e12),
  U("GOOG", "Alphabet Inc. Class C Capital Stock", 2e12),
  U("ZAC", "Zeta Alpha Corp Common Stock", 5e9),
  U("ZBC", "Zeta Beta Corp Common Stock", 4e9),
];
const REGISTERED = new Set(["GP", "N", "DES", "FA", "EQS", "Q"]);
const ctx: NlContext = { isFunction: (c) => REGISTERED.has(c), companies: UNI };

describe("routeNatural", () => {
  it("compare: two names and a range", () => {
    expect(routeNatural("apple vs microsoft 1 year", ctx)).toMatchObject({ kind: "command", command: "AAPL GP 1Y VS MSFT" });
    expect(routeNatural("compare tesla and ford", ctx)).toMatchObject({ kind: "command", command: "TSLA GP VS F" });
  });
  it("compare: an unknown side is named", () => {
    expect(routeNatural("apple vs zzzqqq", ctx)).toEqual({ kind: "error", message: "UNKNOWN COMPANY: ZZZQQQ" });
  });
  // CHANGED ON PURPOSE (NL_V2): "alphabet" is one company now (GOOGL), so the ambiguous example is two similar-size companies.
  it("compare: an ambiguous side offers each reading", () => {
    const r = routeNatural("zeta vs microsoft", ctx);
    expect(r.kind).toBe("choices");
    if (r.kind === "choices") expect(r.choices.map((c) => c.command)).toEqual(["ZAC GP VS MSFT", "ZBC GP VS MSFT"]);
  });
  it("compare: alphabet is one company", () => {
    expect(routeNatural("alphabet vs microsoft", ctx)).toMatchObject({ kind: "command", command: "GOOGL GP VS MSFT" });
  });
  it("screener: sector and price filter", () => {
    expect(routeNatural("tech stocks with price under 50", ctx)).toMatchObject({ kind: "command", command: "EQS tech stocks with price under 50" });
    expect(routeNatural("large cap healthcare stocks", ctx)).toMatchObject({ kind: "command", command: expect.stringMatching(/^EQS /) });
  });
  it("company and intent still win when there is no screener filter", () => {
    expect(routeNatural("apple stock price chart", ctx)).toMatchObject({ kind: "command", command: "AAPL GP" });
    expect(routeNatural("tesla news", ctx).kind).toBe("command");
  });
  it("nothing understood", () => {
    expect(routeNatural("zzzqqq xxyyzz", ctx).kind).toBe("none");
  });
});
