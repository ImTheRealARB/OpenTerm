import { describe, expect, it } from "vitest";
import { searchFunctions, sidebarEnter, symbolCommand } from "./search";

const ITEMS = [
  { code: "GP", title: "Price chart" },
  { code: "GIP", title: "Intraday tick chart" },
  { code: "SECF", title: "Security finder (fuzzy name or ticker search)" },
  { code: "N", title: "News" },
  { code: "FRED", title: "Plot a FRED series" },
];
const isFn = (c: string) => ITEMS.some((i) => i.code === c);

describe("searchFunctions", () => {
  it("puts an exact code first", () => {
    expect(searchFunctions("GP", ITEMS)[0].code).toBe("GP");
  });
  it("matches words in the title", () => {
    expect(searchFunctions("chart", ITEMS).map((i) => i.code).sort()).toEqual(["GIP", "GP"]);
  });
  it("does not match scattered letters (a ticker must not look like a function)", () => {
    expect(searchFunctions("AAPL", ITEMS)).toEqual([]);
  });
  it("returns nothing for an empty query", () => {
    expect(searchFunctions("  ", ITEMS)).toEqual([]);
  });
});

describe("sidebarEnter", () => {
  it("runs multi-word text as typed", () => {
    expect(sidebarEnter("AAPL GP", undefined, isFn)).toBe("AAPL GP");
  });
  it("runs a function code as typed", () => {
    expect(sidebarEnter("gp", ITEMS[0], isFn)).toBe("gp");
  });
  it("runs the top match for a loose word", () => {
    expect(sidebarEnter("chart", ITEMS[0], isFn)).toBe("GP");
  });
  it("falls back to the typed text when nothing matches", () => {
    expect(sidebarEnter("AAPL", undefined, isFn)).toBe("AAPL");
    expect(sidebarEnter("   ", undefined, isFn)).toBeNull();
  });
});

describe("symbolCommand", () => {
  const needs = (c: string) => c === "GP";
  it("keeps a security-based function of the focused panel", () => {
    expect(symbolCommand("aapl", { currentFn: "GP", isFunction: isFn, needsSecurity: needs })).toBe("aapl GP");
  });
  it("uses the plain ticker when the panel function takes no security", () => {
    expect(symbolCommand("AAPL", { currentFn: "N", isFunction: isFn, needsSecurity: needs })).toBe("AAPL");
    expect(symbolCommand("AAPL", { isFunction: isFn, needsSecurity: needs })).toBe("AAPL");
  });
  it("passes spaced text and function codes through untouched", () => {
    expect(symbolCommand("RELIANCE IN GP", { currentFn: "N", isFunction: isFn, needsSecurity: needs })).toBe("RELIANCE IN GP");
    expect(symbolCommand("GP", { currentFn: "GP", isFunction: isFn, needsSecurity: needs })).toBe("GP");
    expect(symbolCommand("", { isFunction: isFn, needsSecurity: needs })).toBeNull();
  });
});
