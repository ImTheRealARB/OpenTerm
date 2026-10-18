import { describe, expect, it } from "vitest";
import type { Universe, UniverseRow } from "./eqsFilter";
import { classify, cusipOk, identsOf, isinOk, sedolOk, yahooSymbol } from "./secfIds";
import { candidatesFromUniverse, mergeSearch, rank, scoreOne, withinOneEdit } from "./secfScore";

const U: Universe = {
  sectors: ["", "Technology", "Real Estate", "Finance"],
  industries: ["", "x", "y", "z"],
  countries: ["", "United States"],
  rows: [
    ["AAPL", "Apple Inc. Common Stock", 200, 1, 0.5, 1, 3.4e12, 1, null, 1, 1],
    ["APLE", "Apple Hospitality REIT, Inc. Common Shares", 15, 0, 0, 1, 3.5e9, 1, null, 2, 2],
    ["AAP", "Advance Auto Parts Inc. Common Stock", 50, 0, 0, 1, 3e9, 1, null, 1, 1],
    ["MSFT", "Microsoft Corporation Common Stock", 400, 0, 0, 1, 3e12, 1, null, 1, 1],
    ["MU", "Micron Technology Inc. Common Stock", 100, 0, 0, 1, 1e11, 1, null, 1, 1],
    ["AMD", "Advanced Micro Devices Inc. Common Stock", 160, 0, 0, 1, 2.6e11, 1, null, 1, 1],
    ["NVDA", "NVIDIA Corporation Common Stock", 180, 0, 0, 1, 4.4e12, 1, null, 1, 1],
    ["JPM", "JP Morgan Chase & Co. Common Stock", 250, 0, 0, 1, 7e11, 1, null, 3, 3],
    ["BRK-B", "Berkshire Hathaway Inc. Class B", 480, 0, 0, 1, 1e12, 1, null, 3, 3],
  ] as UniverseRow[],
};
const CANDS = candidatesFromUniverse(U);
const top = (q: string, n = 3) => rank(CANDS, q).slice(0, n).map((h) => h.symbol);

describe("SECF fuzzy scorer", () => {
  it("an exact symbol beats a prefix, which beats a name match", () => {
    expect(top("aapl")[0]).toBe("AAPL");
    expect(top("aap")).toEqual(["AAP", "AAPL"]);
    expect(top("mu")[0]).toBe("MU");
  });

  it("a name that starts with the word ranks by market cap among equals", () => {
    expect(top("apple")).toEqual(["AAPL", "APLE"]);
    expect(top("micro").slice(0, 2)).toEqual(["MSFT", "MU"]);
  });

  it("a word inside the name matches, lower than a name that starts with it", () => {
    const h = rank(CANDS, "micro");
    expect(h.map((x) => x.symbol)).toContain("AMD");
    expect(h.findIndex((x) => x.symbol === "AMD")).toBeGreaterThan(h.findIndex((x) => x.symbol === "MU"));
  });

  it("every query word must match", () => {
    expect(top("advanced micro")).toEqual(["AMD"]);
    expect(top("micro soft")).toEqual(["MSFT"]);
    expect(rank(CANDS, "apple zebra")).toEqual([]);
  });

  it("tolerates one typo: missing letter, swapped letters, wrong letter", () => {
    expect(top("microsft")[0]).toBe("MSFT");
    expect(top("nvidai")[0]).toBe("NVDA");
    expect(top("nvidoa")[0]).toBe("NVDA");
    expect(top("berkshre")[0]).toBe("BRK-B");
  });

  it("a subsequence of a symbol or a long name still finds it, below the tiers above", () => {
    expect(top("mcrsft")).toContain("MSFT");
    expect(scoreOne("mcrsft", { symbol: "MSFT", name: "Microsoft Corporation" })).toBeLessThan(scoreOne("micro", { symbol: "MSFT", name: "Microsoft Corporation" }));
  });

  it("matches symbols with punctuation and finds nothing for noise", () => {
    expect(top("brk-b")[0]).toBe("BRK-B");
    expect(top("zzzzqq")).toEqual([]);
    expect(rank(CANDS, "   ")).toEqual([]);
  });

  it("the limit caps the list", () => {
    expect(rank(CANDS, "inc", 2)).toHaveLength(2);
  });

  it("withinOneEdit covers insert, delete, replace, swap and rejects two edits", () => {
    expect(withinOneEdit("cat", "cat")).toBe(true);
    expect(withinOneEdit("cat", "cart")).toBe(true);
    expect(withinOneEdit("cart", "cat")).toBe(true);
    expect(withinOneEdit("cat", "cut")).toBe(true);
    expect(withinOneEdit("cat", "act")).toBe(true);
    expect(withinOneEdit("cat", "tac")).toBe(false); // two edits, not one adjacent swap
    expect(withinOneEdit("cat", "cta")).toBe(true);
    expect(withinOneEdit("cat", "dog")).toBe(false);
    expect(withinOneEdit("cat", "carts")).toBe(false);
  });
});

describe("SECF search merge", () => {
  it("a Yahoo hit also in the universe keeps its market cap and says BOTH; a new one says SEARCH", () => {
    const m = mergeSearch(CANDS, [
      { symbol: "AAPL", name: "Apple Inc.", exchange: "NMS", type: "EQUITY", source: "yahoo" },
      { symbol: "RELIANCE.NS", name: "Reliance Industries Limited", exchange: "NSI", type: "EQUITY", source: "yahoo" },
    ]);
    const aapl = m.find((c) => c.symbol === "AAPL")!;
    expect(aapl.src).toBe("BOTH");
    expect(aapl.mcap).toBe(3.4e12);
    expect(aapl.exchange).toBe("NMS");
    const rel = m.find((c) => c.symbol === "RELIANCE.NS")!;
    expect(rel.src).toBe("SEARCH");
    expect(rel.mcap).toBeNull();
    expect(m).toHaveLength(CANDS.length + 1);
    expect(rank(m, "reliance")[0].symbol).toBe("RELIANCE.NS");
  });
});

describe("SECF identifiers", () => {
  it("recognises ISIN, CUSIP, SEDOL and FIGI with their check digits", () => {
    expect(classify("US0378331005")).toEqual({ kind: "ISIN", value: "US0378331005", valid: true });
    expect(classify("037833100")).toEqual({ kind: "CUSIP", value: "037833100", valid: true });
    expect(classify("2046251")).toEqual({ kind: "SEDOL", value: "2046251", valid: true });
    expect(classify("B0YBKJ7")?.valid).toBe(true);
    expect(classify("BBG000B9XRY4")).toEqual({ kind: "FIGI", value: "BBG000B9XRY4", valid: true });
    expect(classify("figi:kkg000000m81")).toEqual({ kind: "FIGI", value: "KKG000000M81", valid: true });
  });

  it("flags a wrong check digit instead of treating the word as a name", () => {
    expect(classify("US0378331006")).toEqual({ kind: "ISIN", value: "US0378331006", valid: false });
    expect(classify("037833101")?.valid).toBe(false);
    expect(classify("2046252")?.valid).toBe(false);
  });

  it("names and tickers are not identifiers", () => {
    for (const w of ["AAPL", "APPLE", "MICROSOFT", "RELIANCE.NS", "BRK-B", "12345", "FIGI:SHORT", ""]) expect(classify(w)).toBeNull();
  });

  it("matches the backend on published values", () => {
    for (const isin of ["US0378331005", "US5949181045", "CH0038863350", "GB0002634946", "INE002A01018"]) expect(isinOk(isin)).toBe(true);
    expect(cusipOk("594918104") && cusipOk("38259P508")).toBe(true);
    expect(sedolOk("0263494")).toBe(true);
  });

  it("a query is an identifier lookup only when every word is one", () => {
    expect(identsOf("US0378331005, 037833100 US0378331005")?.map((i) => i.value)).toEqual(["US0378331005", "037833100"]);
    expect(identsOf("US0378331005 apple")).toBeNull();
    expect(identsOf("")).toBeNull();
    expect(identsOf("apple")).toBeNull();
  });

  it("opens a US listing by its ticker, a mapped foreign one with the Yahoo suffix, and says nothing for an unmapped code", () => {
    expect(yahooSymbol("US", "AAPL")).toBe("AAPL");
    expect(yahooSymbol("UA", "BRK/B")).toBe("BRK/B");
    expect(yahooSymbol("LN", "VOD")).toBe("VOD.L");
    expect(yahooSymbol("HK", "700")).toBe("0700.HK");
    expect(yahooSymbol("IN", "RELIANCE")).toBe("RELIANCE.NS");
    expect(yahooSymbol("XX", "ABC")).toBeNull();
    expect(yahooSymbol(null, "ABC")).toBeNull();
    expect(yahooSymbol("US", null)).toBeNull();
  });
});
