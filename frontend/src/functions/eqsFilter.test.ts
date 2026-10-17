import { describe, expect, it } from "vitest";
import { compileFilter, parseFilter, parseNumber, prefixMatch, screen, type Universe, type UniverseRow } from "./eqsFilter";

// Small hand-made universe in the /api/screener shape (tables index 0 = blank).
const U: Universe = {
  sectors: ["", "Technology", "Consumer Discretionary", "Consumer Staples", "Health Care"],
  industries: ["", "Computer Manufacturing", "Semiconductors", "Packaged Foods", "Auto Manufacturing"],
  countries: ["", "United States", "Taiwan", "United Kingdom"],
  rows: [
    // symbol, name, last, chg, pct, volume, mcap, country, ipo, sector, industry
    ["AAPL", "Apple Inc. Common Stock", 342, -0.96, -0.28, 39_767_602, 4.99e12, 1, 1980, 1, 1],
    ["NVDA", "NVIDIA Corporation Common Stock", 217.23, -4.07, -1.84, 150_000_000, 5.2e12, 1, 1999, 1, 2],
    ["TSM", "Taiwan Semiconductor ADS", 48.5, 1.2, 2.5, 9_000_000, 9e11, 2, 1997, 1, 2],
    ["TSLA", "Tesla Inc. Common Stock", 430, 12.9, 3.1, 80_000_000, 1.4e12, 1, 2010, 2, 4],
    ["KHC", "Kraft Heinz Company", 25.1, 0.6, 2.4, 12_000_000, 3e10, 1, null, 3, 3],
    ["TINY", "Tiny Fund Units", 10, null, null, null, null, 0, null, 0, 0],
  ] as UniverseRow[],
};
const syms = (args: string) => screen(U, parseFilter(args.split(" "))).rows.map((r) => r[0]);

describe("EQS filter grammar", () => {
  it("parses numbers with suffixes", () => {
    expect(parseNumber("10B")).toBe(1e10);
    expect(parseNumber("1.5m")).toBe(1.5e6);
    expect(parseNumber("250K")).toBe(250_000);
    expect(parseNumber("2T")).toBe(2e12);
    expect(parseNumber("2%")).toBe(2);
    expect(parseNumber("$50")).toBe(50);
    expect(parseNumber("-3")).toBe(-3);
    expect(parseNumber("ten")).toBeNull();
    expect(parseNumber("10X")).toBeNull();
  });

  it("parses the example command", () => {
    const f = parseFilter("SECTOR=TECH MCAP>10B PCT>2 PRICE<50 VOL>1M COUNTRY=US".split(" "));
    expect(f.errors).toEqual([]);
    expect(f.clauses.map((c) => c.text)).toEqual(["SECTOR=TECH", "MCAP>10B", "PCT>2", "PRICE<50", "VOL>1M", "COUNTRY=US"]);
    expect(f.clauses[1]).toMatchObject({ kind: "num", field: "MCAP", op: ">", value: 1e10 });
  });

  it("is case-insensitive, takes aliases and spaces around operators", () => {
    const f = parseFilter(["sector", "=", "tech", "cap", ">=", "1t", "last<=400", "%chg!=0"]);
    expect(f.errors).toEqual([]);
    expect(f.clauses.map((c) => c.text)).toEqual(["SECTOR=TECH", "MCAP>=1T", "PRICE<=400", "PCT!=0"]);
  });

  it("reports what it cannot read instead of guessing", () => {
    const f = parseFilter(["FOO>1", "MCAP>lots", "SECTOR>TECH", "SORT=BOGUS", "12"]);
    expect(f.errors).toEqual([
      "UNKNOWN FIELD FOO", "MCAP: LOTS IS NOT A NUMBER", "SECTOR TAKES = OR !=", "CANNOT SORT BY BOGUS", "CANNOT READ 12",
    ]);
    expect(f.clauses).toEqual([]);
  });

  it("matches sectors by prefix of the name or a word", () => {
    expect(prefixMatch("Technology", "tech")).toBe(true);
    expect(prefixMatch("Consumer Staples", "staples")).toBe(true);
    expect(prefixMatch("Health Care", "health c")).toBe(true);
    expect(prefixMatch("Technology", "ology")).toBe(false);
  });

  it("filters rows (all terms ANDed), default sort = market cap desc", () => {
    expect(syms("SECTOR=TECH")).toEqual(["NVDA", "AAPL", "TSM"]);
    expect(syms("SECTOR=TECH COUNTRY=US")).toEqual(["NVDA", "AAPL"]);
    expect(syms("SECTOR=TECH PRICE<50")).toEqual(["TSM"]);
    expect(syms("PCT>2 VOL>10M")).toEqual(["TSLA", "KHC"]);
    expect(syms("MCAP>1T SECTOR!=TECH")).toEqual(["TSLA"]);
    expect(syms("SECTOR=CONSUMER")).toEqual(["TSLA", "KHC"]); // both consumer sectors
    expect(syms("SECTOR=CONSUMER_S")).toEqual(["KHC"]);
    expect(syms("SECTOR=TECH,HEALTH")).toEqual(["NVDA", "AAPL", "TSM"]);
    expect(syms("COUNTRY=TW")).toEqual(["TSM"]);
    expect(syms("COUNTRY=UNITED")).toEqual(["NVDA", "AAPL", "TSLA", "KHC"]); // prefix: United States + Kingdom
    expect(syms("NAME=semi")).toEqual(["TSM"]);
    expect(syms("SEMI")).toEqual(["NVDA", "TSM"]); // bare word -> industry (no sector starts with SEMI)
  });

  it("never lets unknown values pass numeric filters", () => {
    expect(syms("PCT<100")).not.toContain("TINY");
    expect(syms("")).toContain("TINY");
  });

  it("sorts by any key, nulls last", () => {
    expect(syms("SORT=PCT")).toEqual(["TSLA", "TSM", "KHC", "AAPL", "NVDA", "TINY"]);
    expect(syms("SORT=+PCT")).toEqual(["NVDA", "AAPL", "KHC", "TSM", "TSLA", "TINY"]);
    expect(syms("SORT=SYMBOL").slice(0, 3)).toEqual(["AAPL", "KHC", "NVDA"]);
    expect(syms("SECTOR=TECH SORT=-PRICE")).toEqual(["AAPL", "NVDA", "TSM"]);
  });

  it("explains unmatched text values and resolved names", () => {
    const c = compileFilter(parseFilter(["SECTOR=ZZZ", "INDUSTRY=AUTO"]), U);
    expect(c.errors).toEqual(["NO SECTOR MATCHES ZZZ"]);
    expect(c.terms).toEqual(["INDUSTRY=AUTO MANUFACTURING"]);
    expect(syms("SECTOR=ZZZ")).toEqual([]);
  });

  it("filters 10k rows well inside a frame", () => {
    const big: Universe = { ...U, rows: Array.from({ length: 10_000 }, (_, i) => [...U.rows[i % 6]] as UniverseRow) };
    const f = parseFilter("SECTOR=TECH MCAP>10B PCT>-5 VOL>1M COUNTRY=US".split(" "));
    const t0 = performance.now();
    const n = screen(big, f).rows.length;
    const ms = performance.now() - t0;
    expect(n).toBeGreaterThan(0);
    expect(ms).toBeLessThan(16);
  });
});
