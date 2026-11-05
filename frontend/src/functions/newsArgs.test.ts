import { describe, expect, it } from "vitest";
import { newsEmptyHint, newsFilterLine, newsParams, newsQuery, newsTitle } from "./newsArgs";

const AAPL = { symbol: "AAPL" } as never; // the sticky security of the panel

// Table-driven: command words -> query. Pure parsing, so no browser is needed.
describe("newsQuery", () => {
  it.each([
    [[], undefined, { kind: "top" }],
    [["TOP"], AAPL, { kind: "top" }],
    [[], AAPL, { kind: "symbol", symbol: "AAPL" }],
    [["oil", "prices"], undefined, { kind: "keyword", q: "OIL PRICES" }], // bare words keep meaning GDELT keyword search
    [["TECH"], undefined, { kind: "pool", section: "TECH" }],
    [["india"], undefined, { kind: "pool", section: "INDIA" }],
    [["COUNTRY", "in"], undefined, { kind: "pool", region: "IN" }],
    [["REGION", "cn"], undefined, { kind: "pool", region: "CN" }],
    [["SECTOR", "banks"], undefined, { kind: "pool", sector: "BANKS" }],
    [["COMMODITY", "gold"], undefined, { kind: "pool", commodity: "GOLD" }],
    [["SEARCH", "rate", "cut"], undefined, { kind: "pool", q: "rate cut", section: "ALL" }], // text alone searches every feed
    [["TECH", "COUNTRY", "IN", "SEARCH", "chip"], undefined, { kind: "pool", section: "TECH", region: "IN", q: "chip" }],
  ])("%j", (args, security, expected) => {
    expect(newsQuery(args, security)).toEqual(expected);
  });

  it.each([
    [["COUNTRY"], "COUNTRY NEEDS A VALUE"],
    [["SEARCH"], "SEARCH NEEDS 2+ CHARACTERS"],
    [["SEARCH", "x"], "SEARCH NEEDS 2+ CHARACTERS"],
    [["TECH", "banana"], "BANANA IS NOT A NEWS FILTER"],
  ])("%j is an error that says what to fix", (args, text) => {
    const q = newsQuery(args);
    expect(q.kind).toBe("error");
    expect((q as { message: string }).message).toContain(text);
  });
});

describe("newsParams / newsFilterLine / newsTitle", () => {
  it("sends only the filters that were given", () => {
    expect(newsParams(newsQuery(["TECH", "COUNTRY", "IN"]))).toEqual({ section: "TECH", region: "IN" });
    expect(newsParams({ kind: "symbol", symbol: "AAPL" })).toEqual({ symbol: "AAPL" });
    expect(newsParams({ kind: "top" })).toEqual({});
  });
  it("shows the active filters on one line, and nothing for unfiltered views", () => {
    expect(newsFilterLine(newsQuery(["TECH", "COUNTRY", "IN", "SEARCH", "chip"]))).toBe('SECTION TECH · COUNTRY IN · SEARCH "chip"');
    expect(newsFilterLine({ kind: "top" })).toBe("");
    expect(newsFilterLine({ kind: "keyword", q: "OIL" })).toBe("");
  });
  it("titles each view", () => {
    expect(newsTitle({ kind: "top" })).toBe("TOP NEWS");
    expect(newsTitle(newsQuery(["INDIA"]))).toBe("NEWS FEEDS");
  });
  it("names the filters when a feed query comes back empty", () => {
    const h = newsEmptyHint(newsQuery(["SECTOR", "pharma", "SEARCH", "recall"]));
    expect(h).toContain("SECTOR PHARMA");
    expect(h).toContain('SEARCH "recall"');
  });
});
