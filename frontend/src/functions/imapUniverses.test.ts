import { describe, expect, it } from "vitest";
import type { FsrcRow } from "../net/etfTypes";
import type { Coin } from "../net/types";
import { buildImap } from "./imapData";
import { parseFilter } from "./eqsFilter";
import { buildCrypto, buildEtf, buildNifty, parseUniverse, takeLimit, usView } from "./imapUniverses";

const coin = (symbol: string, market_cap: number | null, change_pct_24h: number | null, rank: number): Coin => ({
  symbol, name: `${symbol} coin`, rank, quote: "USD", price: 1, change_pct_1h: null, change_pct_24h, change_pct_7d: null,
  high_24h: null, low_24h: null, volume_24h: null, market_cap, updated: null, source: "coingecko",
});

describe("IMAP universes", () => {
  it("reads the universe word and N= out of the arguments", () => {
    expect(parseUniverse(["crypto", "N=20"])).toEqual({ universe: "CRYPTO", rest: ["N=20"] });
    expect(parseUniverse(["FEE<0.2", "etf"])).toEqual({ universe: "ETF", rest: ["FEE<0.2"] });
    expect(parseUniverse(["SECTOR", "MCAP>10B"])).toEqual({ universe: "US", rest: ["SECTOR", "MCAP>10B"] });
    expect(takeLimit(["CAT=TECH", "N=999"], 150, 200)).toEqual({ limit: 200, rest: ["CAT=TECH"] });
  });

  it("crypto: size is market cap, colour the 24 hour change; a coin with no market cap has no tile and is counted", () => {
    const v = buildCrypto([coin("ETH", 4e11, -1.5, 2), coin("BTC", 1.4e12, 2.5, 1), coin("NOCAP", null, 9, 99)], 50);
    expect(v.rows.map((r) => r.sym)).toEqual(["BTC", "ETH"]); // largest first
    expect(v.rows[0]).toMatchObject({ pct: 2.5, size: 1.4e12, open: "BTC-USD", extra: "RANK 1" });
    expect(v.noSize).toBe(1);
    expect(buildCrypto([coin("ETH", 4e11, -1.5, 2), coin("BTC", 1.4e12, 2.5, 1)], 1)).toMatchObject({ cut: 1 });
  });

  it("ETF: groups by category, sizes by total assets, colours from quotes and never invents a change for a fund with none", () => {
    const funds: FsrcRow[] = [
      ["VOO", "Vanguard S&P 500", 0.03, 1.7e12, "Large Blend", "Vanguard"],
      ["IVV", "iShares Core S&P 500", 0.03, 8.7e11, "Large Blend", "iShares"],
      ["XLK", "Technology SPDR", 0.08, 1.2e11, "Technology", "State Street"],
      ["NOAUM", "No assets reported", 0.5, null, "Technology", null],
    ];
    const v = buildEtf(funds, new Map([["VOO", 0.4], ["XLK", -1.2]]), 150);
    expect(v.groups.map((g) => g.key)).toEqual(["Large Blend", "Technology"]); // the bigger group first
    expect(v.rows.map((r) => [r.sym, r.pct])).toEqual([["VOO", 0.4], ["IVV", null], ["XLK", -1.2]]); // IVV has no quote yet: null
    expect(v.rows[0].extra).toBe("FEE 0.030%");
    expect(v.noSize).toBe(1);
  });

  it("the US map keeps its rows and gives each one its group", () => {
    const u = {
      sectors: ["", "Technology"], industries: [""], countries: [""],
      rows: [["NVDA", "NVIDIA", 180, 3.6, 2.04, 2e8, 4.4e12, 0, 1999, 1, 0], ["NOCAP", "No cap", 5, 0, 0, 1, null, 0, null, 1, 0]] as never,
    };
    const v = usView(buildImap(u, parseFilter([]), { by: "SECTOR", limit: 3000 }));
    expect(v.rows).toEqual([{ sym: "NVDA", name: "NVIDIA", pct: 2.04, size: 4.4e12, group: "Technology", open: "NVDA", extra: "" }]);
    expect(v.noSize).toBe(1);
  });
});

describe("buildNifty", () => {
  it("gives every member an equal tile, grouped by industry, and never invents a change", () => {
    const v = buildNifty(
      [{ symbol: "B.NS", name: "B", industry: "IT" }, { symbol: "A.NS", name: "A", industry: "ENERGY" }, { symbol: "C.NS", name: "C", industry: "IT" }],
      new Map([["A.NS", 1.5], ["B.NS", null]]),
    );
    expect(v.rows.map((r) => [r.sym, r.size, r.pct])).toEqual([["A.NS", 1, 1.5], ["B.NS", 1, null], ["C.NS", 1, null]]);
    expect(v.groups.map((g) => g.key)).toEqual(["IT", "ENERGY"]);
    expect(parseUniverse(["NIFTY500"]).universe).toBe("NIFTY500");
  });
});
