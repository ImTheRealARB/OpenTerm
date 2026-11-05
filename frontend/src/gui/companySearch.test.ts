import { describe, expect, it } from "vitest";
import { cleanName, closestCompanies, type UniverseEntry } from "./companySearch";
import { emptyHeadline, plainLine } from "../components/PanelNote";

describe("emptyHeadline (PanelNote, GUI)", () => {
  it("keeps the first sentence when more follows, else null", () => {
    expect(emptyHeadline("NO WATCHLISTS. WL NAME ADD AAPL MSFT CREATES ONE.")).toBe("NO WATCHLISTS.");
    expect(emptyHeadline("NO HEADLINES.")).toBeNull();
    expect(emptyHeadline("NO HEADLINES")).toBeNull();
    expect(emptyHeadline("")).toBeNull();
  });
});

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

describe("closestCompanies", () => {
  it("prefers lookalikes", () => {
    expect(closestCompanies("TSLQ", U)[0].symbol).toBe("TSLA");
  });
  it("falls back to the biggest names when nothing looks alike", () => {
    const h = closestCompanies("zzzzqq", U, 2);
    expect(h.map((x) => x.symbol)).toEqual(["AAPL", "MSFT"]);
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
