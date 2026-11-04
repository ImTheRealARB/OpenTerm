import { describe, expect, it } from "vitest";
import { cleanName, closestCompanies, enterTarget, matchCompanies, mergeHits, type UniverseEntry } from "./companySearch";
import { plainLine } from "../components/PanelNote";

const U: UniverseEntry[] = [
  { symbol: "AAPL", name: "Apple Inc. Common Stock", mcap: 3e12 },
  { symbol: "APLE", name: "Apple Hospitality REIT, Inc. Common Shares", mcap: 3e9 },
  { symbol: "TSLA", name: "Tesla, Inc. Common Stock", mcap: 8e11 },
  { symbol: "MSFT", name: "Microsoft Corporation Common Stock", mcap: 3e12 },
  { symbol: "NVDA", name: "NVIDIA Corporation Common Stock", mcap: 2e12 },
  { symbol: "PINE", name: "Alpine Income Property Trust, Inc. Common Stock", mcap: 2e8 },
];

describe("cleanName", () => {
  it("drops share-class words", () => {
    expect(cleanName("Apple Inc. Common Stock")).toBe("Apple Inc.");
    expect(cleanName("Foo Ltd. Class A Common Stock")).toBe("Foo Ltd.");
    expect(cleanName("Bar plc American Depositary Shares each representing one")).toBe("Bar plc");
    expect(cleanName("Plain Co")).toBe("Plain Co");
  });
});

describe("matchCompanies", () => {
  it("finds a company by name, biggest first on ties", () => {
    const h = matchCompanies("apple", U);
    expect(h.map((x) => x.symbol)).toEqual(["AAPL", "APLE"]);
    expect(h[0]).toEqual({ symbol: "AAPL", name: "Apple Inc.", via: "name" });
  });
  it("ignores punctuation and case", () => {
    expect(matchCompanies("TESLA,", U)[0].symbol).toBe("TSLA");
    expect(matchCompanies("microsoft corp", U)[0].symbol).toBe("MSFT");
  });
  it("an exact ticker beats name matches, and says via symbol", () => {
    expect(matchCompanies("aapl", U)[0]).toMatchObject({ symbol: "AAPL", via: "symbol" });
  });
  it("matches a ticker prefix", () => {
    expect(matchCompanies("nv", U)[0]).toMatchObject({ symbol: "NVDA", via: "symbol" });
  });
  it("a word in the middle of a name counts, a loose substring needs 3 letters", () => {
    expect(matchCompanies("hospitality", U)[0].symbol).toBe("APLE");
    expect(matchCompanies("pi", U).some((x) => x.symbol === "PINE")).toBe(true); // ticker prefix
    expect(matchCompanies("lp", U)).toEqual([]);
    expect(matchCompanies("lpi", U)[0].symbol).toBe("PINE");
  });
  it("blank query and no match give nothing; limit is respected", () => {
    expect(matchCompanies("  ", U)).toEqual([]);
    expect(matchCompanies("zzzzqq", U)).toEqual([]);
    expect(matchCompanies("a", U, 1)).toHaveLength(1);
  });
});

describe("closestCompanies", () => {
  it("prefers lookalikes", () => {
    expect(closestCompanies("TSLQ", U)[0].symbol).toBe("TSLA");
  });
  it("falls back to the biggest names when nothing looks alike", () => {
    const h = closestCompanies("zzzzqq", U, 2);
    expect(h.map((x) => x.symbol)).toEqual(["AAPL", "MSFT"]);
  });
});

describe("enterTarget / mergeHits", () => {
  const hits = matchCompanies("apple", U);
  it("runs the top ticker when the match was by name", () => {
    expect(enterTarget("apple", hits)).toBe("AAPL");
  });
  it("keeps typed text for a ticker, a prefix, spaces or no suggestions", () => {
    expect(enterTarget("aapl", matchCompanies("aapl", U))).toBe("aapl");
    expect(enterTarget("nv", matchCompanies("nv", U))).toBe("nv");
    expect(enterTarget("RELIANCE IN", [])).toBe("RELIANCE IN");
    expect(enterTarget("zzzzqq", [])).toBe("zzzzqq");
  });
  it("mergeHits keeps the first of each ticker", () => {
    expect(mergeHits(hits, [{ symbol: "AAPL", name: "x", via: "name" }, { symbol: "NEW", name: "n", via: "name" }]).map((h) => h.symbol)).toEqual(["AAPL", "APLE", "NEW"]);
  });
});

describe("plainLine (PanelNote)", () => {
  it("only for error and stale", () => {
    expect(plainLine("loading", "LOADING")).toBeNull();
    expect(plainLine("empty", "NO HEADLINES")).toBeNull();
  });
  it("names the source and the age", () => {
    expect(plainLine("error", "ERR: yahoo timed out, last data 4 min OLD")).toMatch(/^Yahoo isn't answering right now\. Data shown is 4 min old\. It retries on its own\.$/);
    expect(plainLine("stale", "STALE: NASDAQ 12 s OLD")).toMatch(/Nasdaq is slow to answer\. Data shown is 12 s old/);
  });
  it("handles keys and missing data", () => {
    expect(plainLine("error", "KEY REQUIRED: set X in APIKEYS")).toMatch(/free API key/);
    expect(plainLine("error", "NO DATA FOR ZZ")).toMatch(/nothing for that/);
    expect(plainLine("error", "ERR: boom")).toMatch(/^The data source isn't answering/);
  });
});
