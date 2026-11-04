import { describe, expect, it } from "vitest";
import { INDICATORS } from "../chart/indicators";
import { RANGES } from "../functions/gpArgs";
import type { UniverseEntry } from "../gui/companySearch";
import { parseCommand } from "./parser";
import { GP_RANGES, interpretNatural, type NlContext, type NlResult } from "./natural";

const U = (symbol: string, name: string, mcap: number | null): UniverseEntry => ({ symbol, name, mcap });
const UNI: UniverseEntry[] = [
  U("AAPL", "Apple Inc. Common Stock", 3e12),
  U("APLE", "Apple Hospitality REIT, Inc. Common Shares", 3e9),
  U("MSFT", "Microsoft Corporation Common Stock", 3.1e12),
  U("NVDA", "NVIDIA Corporation Common Stock", 3.3e12),
  U("TSLA", "Tesla, Inc. Common Stock", 8e11),
  U("AMZN", "Amazon.com, Inc. Common Stock", 1.9e12),
  U("META", "Meta Platforms, Inc. Class A Common Stock", 1.3e12),
  U("GOOGL", "Alphabet Inc. Class A Common Stock", 2e12),
  U("GOOG", "Alphabet Inc. Class C Capital Stock", 2e12),
  U("BAC", "Bank of America Corporation Common Stock", 3e11),
  U("BK", "Bank of New York Mellon Corporation Common Stock", 5e10),
  U("OZK", "Bank OZK Common Stock", 6e9),
  U("JPM", "JPMorgan Chase & Co. Common Stock", 6e11),
  U("KO", "Coca-Cola Company (The) Common Stock", 2.6e11),
  U("BRK-B", "Berkshire Hathaway Inc. Class B Common Stock", 9e11),
  U("F", "Ford Motor Company Common Stock", 4e10),
];
const REGISTERED = new Set(["GP", "N", "DES", "FA", "FIL", "OWN", "HDS", "COMP", "SEAS", "DVD", "Q"]);
const ctx: NlContext = { isFunction: (c: string) => REGISTERED.has(c), companies: UNI };
const run = (s: string, c = ctx): NlResult => interpretNatural(s, c);
const cmd = (s: string, c = ctx) => {
  const r = run(s, c);
  return r.kind === "command" ? r.command : r.kind;
};

describe("natural language phrase table", () => {
  const table: [string, string][] = [
    ["apple stock price chart", "AAPL GP"],
    ["tesla news", "TSLA N"],
    ["microsoft 5 year chart", "MSFT GP 5Y"],
    ["apple", "AAPL"],
    ["Apple", "AAPL"],
    ["nvidia financials", "NVDA FA"],
    ["amazon balance sheet", "AMZN FA BS"],
    ["amazon income statement", "AMZN FA IS"],
    ["amazon cash flow", "AMZN FA CF"],
    ["amazon quarterly cash flow", "AMZN FA Q CF"],
    ["show me the apple chart with rsi", "AAPL GP RSI"],
    ["apple chart", "AAPL GP"],
    ["chart of apple", "AAPL GP"],
    ["what's the apple stock price", "AAPL GP"],
    ["how is tesla doing", "TSLA"],
    ["tesla stock", "TSLA GP"],
    ["apple graph 1 month", "AAPL GP 1M"],
    ["apple 6 months", "AAPL GP 6M"],
    ["apple 1 year chart", "AAPL GP 1Y"],
    ["apple 10y chart", "AAPL GP 10Y"],
    ["apple ytd", "AAPL GP YTD"],
    ["apple all time chart", "AAPL GP MAX"],
    ["apple max chart", "AAPL GP MAX"],
    ["apple today", "AAPL GP 1D"],
    ["apple intraday chart", "AAPL GP 1D"],
    ["apple 1 week chart", "AAPL GP 5D"],
    ["apple candlestick chart", "AAPL GP CANDLE"],
    ["apple line chart", "AAPL GP LINE"],
    ["apple area chart 5 years", "AAPL GP 5Y AREA"],
    ["apple log chart", "AAPL GP LOG"],
    ["apple chart moving average 50", "AAPL GP SMA50"],
    ["apple 50 day moving average", "AAPL GP SMA50"],
    ["apple chart with bollinger bands", "AAPL GP BB"],
    ["apple macd and rsi", "AAPL GP RSI MACD"],
    ["apple rsi", "AAPL GP RSI"],
    ["msft overview", "MSFT DES"],
    ["tell me about nvidia", "NVDA"],
    ["nvidia company profile", "NVDA DES"],
    ["apple filings", "AAPL FIL"],
    ["apple 10-k", "AAPL FIL"],
    ["apple holders", "AAPL HDS"],
    ["apple ownership", "AAPL OWN"],
    ["apple peers", "AAPL COMP"],
    ["apple competitors", "AAPL COMP"],
    ["apple seasonality", "AAPL SEAS"],
    ["apple dividends", "AAPL DVD"],
    ["meta platforms news", "META N"],
    ["bank of america chart", "BAC GP"],
    ["bank of america", "BAC"],
    ["aapl chart", "AAPL GP"],
    ["tsla 5y", "TSLA GP 5Y"],
    ["brk-b news", "BRK-B N"],
    ["coca cola news", "KO N"],
    ["coca-cola news", "KO N"],
    ["news", "N"],
    ["show me the news", "N"],
    ["chart", "GP"],
    ["xyzzy blorp", "none"],
    ["", "none"],
  ];
  it.each(table)("%s -> %s", (input, want) => {
    expect(cmd(input)).toBe(want);
  });

  it("does not use a function that is not registered", () => {
    const small = { isFunction: (c: string) => c === "GP" || c === "DES", companies: UNI };
    expect(cmd("apple dividends", small)).toBe("AAPL"); // no DVD: the words are dropped, the company stays
    expect(cmd("apple holders", small)).toBe("AAPL");
    expect(cmd("apple ownership", { ...small, isFunction: (c: string) => c === "OWN" })).toBe("AAPL OWN");
    expect(cmd("apple holders", { ...small, isFunction: (c: string) => c === "OWN" })).toBe("AAPL OWN"); // HDS missing -> OWN
  });

  it("explains itself", () => {
    const r = run("apple stock price chart");
    expect(r.kind === "command" && r.why).toBe("AAPL GP");
  });

  it("works for intent-only phrases before the company list is loaded", () => {
    expect(cmd("news", { ...ctx, companies: null })).toBe("N");
    expect(cmd("apple chart", { ...ctx, companies: null })).toBe("none");
  });
});

describe("ambiguity", () => {
  it("asks between share classes of one company", () => {
    const r = run("alphabet");
    expect(r.kind).toBe("choices");
    if (r.kind === "choices") expect(r.choices.map((c) => c.command).sort()).toEqual(["GOOG", "GOOGL"]);
  });

  it("keeps the intent in every choice", () => {
    const r = run("alphabet 5 year chart");
    expect(r.kind === "choices" && r.choices.map((c) => c.command).sort()).toEqual(["GOOG GP 5Y", "GOOGL GP 5Y"]);
  });

  it("asks when several similar-size companies match", () => {
    const r = run("bank");
    expect(r.kind).toBe("choices");
    if (r.kind === "choices") {
      expect(r.choices.length).toBeLessThanOrEqual(5);
      expect(r.choices.map((c) => c.command)).toContain("BAC");
    }
  });

  it("picks the clearly biggest company (apple is not Apple Hospitality)", () => {
    expect(cmd("apple")).toBe("AAPL");
  });

  it("an exact ticker wins over names", () => {
    expect(cmd("f chart")).toBe("F GP");
  });

  it("never offers more than five", () => {
    const many = Array.from({ length: 20 }, (_, i) => U(`ZB${i}`, `Zeta Bank ${i} Inc.`, 1e9));
    const r = interpretNatural("zeta", { isFunction: ctx.isFunction, companies: many });
    expect(r.kind === "choices" && r.choices.length).toBe(5);
  });
});

describe("exact codes are never reinterpreted", () => {
  // The integration rule lives in nlRun.needsNatural; here the seam is the grammar itself: these all parse.
  it.each(["AAPL GP", "AAPL", "GP", "MSFT GP 5Y", "AAPL N", "2: AAPL GP"])("%s is valid grammar", (s) => {
    expect(parseCommand(s, ctx.isFunction).ok).toBe(true);
  });
  it.each(["apple chart", "tesla news"])("%s is not valid grammar (natural language gets its turn)", (s) => {
    expect(parseCommand(s, ctx.isFunction).ok).toBe(false);
  });
});

describe("tables stay in step with GP", () => {
  it("ranges", () => expect(GP_RANGES).toEqual(RANGES));
  it("every command it produces is accepted by the grammar and GP", () => {
    for (const s of ["apple chart rsi macd", "apple 5y area log chart", "apple moving average 50", "amazon quarterly balance sheet"]) {
      const c = cmd(s);
      expect(parseCommand(c, (x) => REGISTERED.has(x)).ok).toBe(true);
    }
    for (const i of ["BB", "RSI", "MACD", "VWAP", "ATR", "STOCH", "ADX", "OBV", "CCI", "ICHIMOKU", "SUPERTREND", "PSAR", "SMA20", "SMA50", "EMA20"]) {
      expect(INDICATORS as readonly string[]).toContain(i);
    }
  });
});
