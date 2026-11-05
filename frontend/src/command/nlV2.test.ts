import { describe, expect, it } from "vitest";
import { INDICATORS } from "../chart/indicators";
import { RANGES } from "../functions/gpArgs";
import { closestCompanies, editDistance, isCompanyShare, type UniverseEntry } from "../gui/companySearch";
import { closestAliases, fxPair, lookupAlias } from "./nlAliases";
import { interpretNatural, type NlContext } from "./natural";
import { routeNatural } from "./nlRoute";
import { pickRemote } from "./nlRemote";
import { coverMonths, extractRange, GP_RANGES } from "./nlRange";

/**
 * Plain-English commands v2 (docs/specs/NL_V2.md): one test per row of the spec's failure table, plus ranges, indicators,
 * intents, several companies without "vs", typos and speed. The company list is a SMALL hand-written copy of how the real
 * screener names things (Nasdaq style names, `BRK/B` share-class spelling, preferred shares next to the common stock).
 */

const U = (symbol: string, name: string, mcap: number | null, volume = 1_000_000): UniverseEntry => ({ symbol, name, mcap, volume });
const UNI: UniverseEntry[] = [
  U("AAPL", "Apple Inc. Common Stock", 4.8e12, 63e6),
  U("APLE", "Apple Hospitality REIT Inc. Common Shares", 4.4e9, 2e6),
  U("MSFT", "Microsoft Corporation Common Stock", 3.9e12, 20e6),
  U("NVDA", "NVIDIA Corporation Common Stock", 4.5e12, 150e6),
  U("TSLA", "Tesla, Inc. Common Stock", 1.4e12, 90e6),
  U("AMZN", "Amazon.com, Inc. Common Stock", 2.4e12, 40e6),
  U("META", "Meta Platforms Inc. Class A Common Stock", 1.6e12, 13e6),
  U("GOOGL", "Alphabet Inc. Class A Common Stock", 3.44e12, 35e6),
  U("GOOG", "Alphabet Inc. Class C Capital Stock", 3.42e12, 23e6),
  U("GOOGM", "Alphabet Inc. Depositary Shares representing a 1/20th Interest in a Share of Series A Mandatory Convertible Preferred Stock", null, 1e3),
  U("BRK/A", "Berkshire Hathaway Inc.", 1.23e12, 308),
  U("BRK/B", "Berkshire Hathaway Inc.", 1.23e12, 5.5e6),
  U("BAC", "Bank of America Corporation Common Stock", 3.4e11, 50e6),
  U("BAC^B", "Bank of America Corporation Depositary Shares each representing a 1/1000th interest in a share of 6.000% Non-Cumulative Preferred Stock Series GG", null, 2e5),
  U("BK", "Bank of New York Mellon Corporation Common Stock", 6e10, 5e6),
  U("JPM", "JP Morgan Chase & Co. Common Stock", 8e11, 9e6),
  U("JPM^J", "JP Morgan Chase & Co. Depositary Shares, each representing a one four hundredth interest in a share of 4.55% Preferred Stock", null, 1e5),
  U("KO", "Coca-Cola Company (The) Common Stock", 4.1e11, 16e6),
  U("COKE", "Coca-Cola Consolidated Inc. Common Stock", 1e10, 1e5),
  U("CCEP", "Coca-Cola Europacific Partners plc Ordinary Shares", 4e10, 1e6),
  U("KOF", "Coca Cola Femsa S.A.B. de C.V. American Depositary Shares each representing 10 Units (each Unit consists of 3 Series B Shares and 5 Series L Shares)", 1.5e10, 1e5),
  U("HAS", "Hasbro Inc. Common Stock", 1.6e10, 1.5e6),
  U("RS", "Reliance Inc. Common Stock", 2.2e10, 3e5),
  U("MCD", "McDonald's Corporation Common Stock", 1.86e11, 6e6),
  U("KSS", "Kohl's Corporation Common Stock", 3e9, 8e6),
  U("F", "Ford Motor Company Common Stock", 4.9e10, 40e6),
  U("AMD", "Advanced Micro Devices Inc. Common Stock", 3e11, 40e6),
  U("INTC", "Intel Corporation Common Stock", 2e11, 80e6),
  U("NOW", "ServiceNow, Inc. Common Stock", 1.8e11, 1.5e6),
  U("ALL", "Allstate Corporation (The) Common Stock", 5e10, 1.5e6),
  U("IT", "Gartner, Inc. Common Stock", 3e10, 5e5),
  U("SPGI", "S&P Global Inc. Common Stock", 1.5e11, 1e6),
  U("NDAQ", "Nasdaq, Inc. Common Stock", 5e10, 3e6),
  U("DOW", "Dow Inc. Common Stock", 2e10, 8e6),
  U("GOLD", "Barrick Mining Corporation Common Stock", 3e10, 2e7),
  U("POR", "Portland General Electric Company Common Stock", 5e9, 1e6),
  U("ZAC", "Zeta Alpha Corp Common Stock", 5e9),
  U("ZBC", "Zeta Beta Corp Common Stock", 4e9),
  U("ABCDU", "Abcd Acquisition Corp. Units", 1e8, 100),
  U("ABCDW", "Abcd Acquisition Corp. Warrant", null, 100),
  U("SOFT", "Software Acquisition Group Inc. Common Stock", 2e8, 1e4),
];
const FUNCS = new Set(["GP", "N", "DES", "FA", "FIL", "OWN", "HDS", "COMP", "SEAS", "DVD", "Q", "EE", "ANR", "OMON", "ERN"]);
const NOW = new Date("2026-11-05T12:00:00Z");
const ctx: NlContext = { isFunction: (c) => FUNCS.has(c), companies: UNI, now: NOW };
/** The command the router gives for a sentence ("choices ..." / "none" / "error ..." when it is not one command). */
const cmd = (s: string, c: NlContext = ctx): string => {
  const r = routeNatural(s, c);
  return r.kind === "command" ? r.command : r.kind === "choices" ? `choices ${r.choices.map((x) => x.command).join(" | ")}` : r.kind === "error" ? `error ${r.message}` : "none";
};

describe("NL_V2 failure table: every row", () => {
  const rows: [string, string][] = [
    ["how has apple done over 5 years", "AAPL GP 5Y"], // v1: HAS GP 5Y (Hasbro)
    ["show me apple's stock for the last 5 years", "AAPL GP 5Y"], // v1: "apples"
    ["google stock price", "GOOGL GP"],
    ["facebook stock", "META GP"],
    ["mcdonalds chart", "MCD GP"],
    ["alphabet stock", "GOOGL GP"], // most traded class
    ["berkshire stock", "BRK-B GP"],
    ["bank of america news", "BAC N"], // not the preferred BAC^B
    ["jpmorgan 5 years", "JPM GP 5Y"],
    ["coca cola stock", "KO GP"], // exact core name beats Coca-Cola Consolidated and friends
    ["s&p 500", "^GSPC"],
    ["sp500 chart", "^GSPC GP"],
    ["nasdaq", "^IXIC"],
    ["dow jones", "^DJI"],
    ["gold price", "GC=F GP"],
    ["oil price", "CL=F GP"],
    ["bitcoin price", "BTC-USD GP"],
    ["ethereum", "ETH-USD"],
    ["eur usd", "EURUSD=X"],
    ["dollar rupee", "USDINR=X"],
    ["reliance stock price", "RELIANCE.NS GP"],
    ["tata motors", "TATAMOTORS.NS"],
    ["nifty 50", "^NSEI"],
    ["sensex", "^BSESN"],
    ["apple past six months", "AAPL GP 6M"],
    ["apple last 4 years", "AAPL GP 5Y"],
    ["apple 18 months", "AAPL GP 2Y"],
    ["apple 20 years", "AAPL GP MAX"],
    ["apple last quarter", "AAPL GP 3M"],
    ["apple since 2020", "AAPL GP 10Y"],
    ["apple from 2019 to 2023", "AAPL GP 10Y"],
    ["apple since ipo", "AAPL GP MAX"],
    ["apple 200 day moving average", "AAPL GP SMA200"],
    ["apple microsoft nvidia 1 year", "AAPL GP 1Y VS MSFT NVDA"],
    ["mircosoft stock", "choices MSFT GP"], // "did you mean"
    ["apple pe ratio", "AAPL DES"],
    ["apple market cap", "AAPL DES"],
  ];
  it.each(rows)("%s -> %s", (input, want) => {
    expect(cmd(input)).toBe(want);
  });

  it("BRK/B from the screener is spelled BRK-B (a valid symbol token)", () => {
    expect(cmd("berkshire hathaway")).toBe("BRK-B");
    expect(cmd("brk/b chart")).toBe("BRK-B GP");
  });
});

describe("company names", () => {
  it("lower-case common English words are not tickers, capitals are", () => {
    expect(cmd("how has apple done")).toBe("AAPL");
    expect(cmd("has")).toBe("none");
    expect(cmd("now")).toBe("none");
    expect(cmd("HAS stock price")).toBe("HAS GP");
    expect(cmd("NOW stock")).toBe("NOW GP");
    expect(cmd("hasbro stock")).toBe("HAS GP");
  });
  it("a partial word is a question, never a silent pick", () => {
    expect(cmd("micros stock")).toBe("choices MSFT GP");
    expect(cmd("weath")).toBe("none");
  });
  it("a name found only late inside another name is asked about, not run", () => {
    expect(cmd("general electric")).toBe("GE"); // alias for GE Aerospace
    expect(cmd("portland general")).toBe("POR"); // starts the name: fine
    expect(cmd("electric company")).toMatch(/^choices /);
  });
  it("preferred shares, warrants, rights and SPAC units never match a name", () => {
    const bad = UNI.filter((e) => !isCompanyShare(e)).map((e) => e.symbol);
    expect(bad).toEqual(expect.arrayContaining(["BAC^B", "JPM^J", "GOOGM", "ABCDU", "ABCDW", "KOF"]));
    expect(bad).not.toContain("BAC");
    expect(cmd("abcd")).toBe("none");
  });
  it("different companies of similar size are still a question", () => {
    expect(cmd("zeta")).toBe("choices ZAC | ZBC");
    expect(cmd("bank")).toMatch(/^choices BAC/);
  });
  it("possessives work in both directions", () => {
    expect(cmd("kohl's stock")).toBe("KSS GP");
    expect(cmd("mcdonald's")).toBe("MCD");
    expect(cmd("tesla's chart")).toBe("TSLA GP");
  });
  it("a dot inside a name is fine (amazon.com)", () => {
    expect(cmd("amazon.com stock")).toBe("AMZN GP");
  });
  it("class letters are part of the name", () => {
    expect(cmd("alphabet class c")).toBe("GOOG");
    expect(cmd("berkshire hathaway class a")).toBe("BRK-A");
  });
  it("3m is the company when nothing else is named", () => {
    expect(cmd("3m stock")).toBe("MMM GP");
    expect(cmd("apple 3m")).toBe("AAPL GP 3M");
  });
  it("works before the company list is loaded for names the alias table knows", () => {
    const noList = { ...ctx, companies: null };
    expect(cmd("gold price", noList)).toBe("GC=F GP");
    expect(cmd("apple chart", noList)).toBe("none");
  });
});

describe("aliases", () => {
  it("indices, commodities, crypto and the Indian large caps use the boards' symbols", () => {
    const want: [string, string][] = [
      ["nasdaq 100", "^NDX"], ["nikkei", "^N225"], ["ftse 100", "^FTSE"], ["bank nifty", "^NSEBANK"],
      ["silver", "SI=F"], ["brent crude", "BZ=F"], ["natural gas", "NG=F"], ["copper", "HG=F"],
      ["solana", "SOL-USD"], ["doge", "DOGE-USD"], ["xrp", "XRP-USD"],
      ["infosys", "INFY.NS"], ["hdfc bank", "HDFCBANK.NS"], ["tcs", "TCS.NS"], ["state bank of india", "SBIN.NS"], ["larsen and toubro", "LT.NS"],
    ];
    for (const [phrase, symbol] of want) expect(cmd(phrase)).toBe(symbol);
  });
  it("the why names the exchange for an Indian company", () => {
    const r = routeNatural("reliance stock price", ctx);
    expect(r.kind === "command" && r.why).toContain("NSE");
  });
  it("every alias symbol is a valid command token", () => {
    for (const s of ["^GSPC", "GC=F", "BTC-USD", "EURUSD=X", "RELIANCE.NS", "M&M.NS", "BAJAJ-AUTO.NS", "DX-Y.NYB"]) {
      expect(/^[A-Z0-9^][A-Z0-9.\-=^&]*$/.test(s)).toBe(true);
    }
    expect(lookupAlias("m&m")?.symbol).toBe("M&M.NS");
  });
  it("currencies: codes, words, glued codes, either order, 'to'", () => {
    expect(fxPair("usd inr")?.symbol).toBe("USDINR=X");
    expect(fxPair("eurusd")?.symbol).toBe("EURUSD=X");
    expect(fxPair("eur/usd")?.symbol).toBe("EURUSD=X");
    expect(fxPair("pound to dollar")?.symbol).toBe("GBPUSD=X");
    expect(fxPair("rupee dollar")?.symbol).toBe("INRUSD=X");
    expect(fxPair("aud nzd")?.symbol).toBe("AUDNZD=X");
    expect(fxPair("hong kong dollar yen")?.symbol).toBe("HKDJPY=X");
    expect(fxPair("rupee")?.symbol).toBe("USDINR=X"); // a lone currency is quoted against the dollar
    expect(fxPair("euro")?.symbol).toBe("EURUSD=X");
    expect(fxPair("yen")?.symbol).toBe("USDJPY=X");
  });
  it("English words that are also currency names are not currencies on their own", () => {
    expect(fxPair("won")).toBeNull();
    expect(fxPair("dollar")).toBeNull();
    expect(fxPair("usd stock")).toBeNull();
    expect(cmd("who won")).toBe("none");
  });
  it("'dollar vs rupee' is an exchange rate, not a compare", () => {
    expect(cmd("dollar vs rupee")).toBe("USDINR=X");
    expect(cmd("usd vs inr 5 years")).toBe("USDINR=X GP 5Y");
  });
  it("a mistyped alias gets 'did you mean'", () => {
    expect(closestAliases("googel").map((a) => a.symbol)).toContain("GOOGL");
    expect(cmd("googel stock")).toBe("choices GOOGL GP");
    expect(cmd("bitcon")).toBe("choices BTC-USD");
  });
});

describe("ranges", () => {
  it("number words up to twenty and 'a couple of'", () => {
    expect(cmd("apple past six months")).toBe("AAPL GP 6M");
    expect(cmd("apple twenty years")).toBe("AAPL GP MAX");
    expect(cmd("apple for a couple of years")).toBe("AAPL GP 2Y");
    expect(cmd("apple five years")).toBe("AAPL GP 5Y");
    expect(cmd("apple a year")).toBe("AAPL GP 1Y");
    expect(cmd("apple in the last twelve months")).toBe("AAPL GP 1Y");
  });
  it("a range GP lacks becomes the smallest one that covers it, and the why says so", () => {
    const cases: [string, string][] = [
      ["apple 4 years", "5Y"], ["apple 3 years", "5Y"], ["apple 7 years", "10Y"], ["apple 12 years", "MAX"], ["apple 18 months", "2Y"],
      ["apple 9 months", "1Y"], ["apple 5 months", "6M"], ["apple 2 weeks", "1M"], ["apple 10 days", "1M"], ["apple 3 days", "5D"],
      ["apple 1.5 years", "2Y"], ["apple 2 decades", "MAX"],
    ];
    for (const [input, range] of cases) {
      const r = routeNatural(input, ctx);
      expect(r.kind === "command" && r.command).toBe(`AAPL GP ${range}`);
      expect(r.kind === "command" && r.why).toContain("the closest range");
    }
  });
  it("an exact fit has no apology", () => {
    const r = routeNatural("apple 5 years", ctx);
    expect(r.kind === "command" && r.why).toBe("AAPL GP");
  });
  it("since <year>, from <year> (to <year>), <n> years ago", () => {
    const r = routeNatural("apple since 2020", ctx);
    expect(r.kind === "command" && r.why).toBe("AAPL GP · since 2020: 10Y, the closest range");
    expect(cmd("apple since 2025")).toBe("AAPL GP 2Y");
    expect(cmd("apple since 2024")).toBe("AAPL GP 5Y");
    expect(cmd("apple since march 2026")).toBe("AAPL GP 1Y");
    expect(cmd("apple from 2019 to 2023")).toBe("AAPL GP 10Y");
    expect(cmd("apple from 2022")).toBe("AAPL GP 5Y");
    expect(cmd("tesla stock price 5 years ago")).toBe("TSLA GP 5Y");
    expect(cmd("apple since 2999")).toBe("AAPL"); // a future year is ignored
    const to = routeNatural("apple from 2019 to 2023", ctx);
    expect(to.kind === "command" && to.why).toContain("GP always ends today");
  });
  it("since ipo / inception / listing = MAX", () => {
    for (const s of ["apple since ipo", "apple since inception", "apple since listing", "apple from the start"]) expect(cmd(s)).toBe("AAPL GP MAX");
  });
  it("this year is year-to-date, last year is 1Y, last quarter is 3M (but quarterly financials stay financials)", () => {
    expect(cmd("how did tesla do this year")).toBe("TSLA GP YTD");
    expect(cmd("tesla last year")).toBe("TSLA GP 1Y");
    expect(cmd("apple last quarter")).toBe("AAPL GP 3M");
    expect(cmd("apple revenue last quarter")).toBe("AAPL FA Q");
  });
  it("compare sentences read ranges the same way", () => {
    expect(cmd("apple vs microsoft since 2021")).toBe("AAPL GP 10Y VS MSFT");
    expect(cmd("apple vs microsoft five years")).toBe("AAPL GP 5Y VS MSFT");
    expect(cmd("apple vs microsoft 18 months")).toBe("AAPL GP 2Y VS MSFT");
    expect(cmd("apple vs microsoft")).toBe("AAPL GP VS MSFT");
  });
  it("coverMonths and extractRange", () => {
    expect(coverMonths(1)).toBe("1M");
    expect(coverMonths(1.1)).toBe("3M");
    expect(coverMonths(121)).toBe("MAX");
    const st = { s: " apple over the last 5 years " };
    expect(extractRange(st, NOW)).toEqual({ range: "5Y" });
    expect(st.s.trim()).toBe("apple");
    expect(extractRange({ s: " apple " }, NOW)).toBeNull();
  });
  it("every range it can return exists in GP", () => {
    expect(GP_RANGES).toEqual(RANGES);
  });
});

describe("indicators", () => {
  it("the chart has the new averages, appended so old picker keys keep working", () => {
    for (const i of ["SMA100", "SMA200", "EMA50", "EMA200"]) expect(INDICATORS as readonly string[]).toContain(i);
    expect(INDICATORS[0]).toBe("SMA20"); // key 1
    expect(INDICATORS[4]).toBe("RSI"); // key 5 (gp-toggle e2e)
    expect(INDICATORS[5]).toBe("MACD"); // key 6
  });
  it("phrases for each average", () => {
    expect(cmd("apple 200 day moving average")).toBe("AAPL GP SMA200");
    expect(cmd("apple 100 day moving average")).toBe("AAPL GP SMA100");
    expect(cmd("apple sma 100")).toBe("AAPL GP SMA100");
    expect(cmd("apple ema 50")).toBe("AAPL GP EMA50");
    expect(cmd("apple 50 day ema")).toBe("AAPL GP EMA50");
    expect(cmd("apple ema200 chart 2 years")).toBe("AAPL GP 2Y EMA200");
    expect(cmd("apple 200-day moving average")).toBe("AAPL GP SMA200");
    expect(cmd("apple 200 dma")).toBe("AAPL GP SMA200");
    expect(cmd("apple exponential moving average 20")).toBe("AAPL GP EMA20");
    expect(cmd("apple 50 day and 200 day moving average")).toBe("AAPL GP SMA50 SMA200");
  });
  it("an average the chart cannot draw is said, not silently dropped", () => {
    const r = routeNatural("apple 21 day moving average", ctx);
    expect(r.kind === "command" && r.why).toContain("SMA21 is not on the chart");
  });
  it("an average is not mistaken for a number of days", () => {
    expect(cmd("apple 200 day moving average 1 year")).toBe("AAPL GP 1Y SMA200");
  });
});

describe("more intents (only functions that exist)", () => {
  const rows: [string, string][] = [
    ["apple pe ratio", "AAPL DES"], ["tesla p/e", "TSLA DES"], ["apple price to earnings", "AAPL DES"], ["apple valuation", "AAPL DES"],
    ["what is apple's market cap", "AAPL DES"], ["what is microsoft worth", "MSFT DES"],
    ["nvidia analyst ratings", "NVDA ANR"], ["microsoft analyst price target", "MSFT ANR"], ["apple upgrades", "AAPL ANR"],
    ["apple eps estimates", "AAPL EE"], ["apple earnings estimates", "AAPL EE"], ["apple consensus", "AAPL EE"],
    ["apple options", "AAPL OMON"], ["tesla option chain", "TSLA OMON"],
    ["what's new with apple", "AAPL N"], ["whats happening with tesla", "TSLA N"], ["latest on nvidia", "NVDA N"],
    ["apple earnings", "AAPL FA"], ["apple dividend yield", "AAPL DVD"],
  ];
  it.each(rows)("%s -> %s", (input, want) => expect(cmd(input)).toBe(want));
  it("no earnings-date screen exists: the words are dropped and the why says so", () => {
    const r = routeNatural("apple earnings date", ctx);
    expect(r.kind === "command" && r.command).toBe("AAPL");
    expect(r.kind === "command" && r.why).toContain("next earnings date");
  });
  it("an intent whose function is missing is skipped", () => {
    const small: NlContext = { ...ctx, isFunction: (c) => c === "GP" || c === "DES" };
    expect(cmd("apple analyst ratings", small)).toBe("AAPL");
    expect(cmd("apple pe ratio", small)).toBe("AAPL DES");
  });
});

describe("several companies without 'vs'", () => {
  it("become one compare chart", () => {
    expect(cmd("apple microsoft nvidia 1 year")).toBe("AAPL GP 1Y VS MSFT NVDA");
    expect(cmd("tesla and ford")).toBe("TSLA GP VS F");
    expect(cmd("apple, microsoft, and google 5 years")).toBe("AAPL GP 5Y VS MSFT GOOGL");
    expect(cmd("compare reliance tata motors")).toBe("RELIANCE.NS GP VS TATAMOTORS.NS");
  });
  it("GP takes the first plus three: more names are cut and the why says so", () => {
    const r = routeNatural("apple microsoft nvidia tesla ford", ctx);
    expect(r.kind === "command" && r.command).toBe("AAPL GP VS MSFT NVDA TSLA");
    expect(r.kind === "command" && r.why).toContain("at most 4");
  });
  it("a small unknown name next to a famous one is not turned into a compare", () => {
    expect(cmd("apple software")).toBe("AAPL");
    expect(cmd("apple news microsoft")).toBe("AAPL N");
  });
  it("only for charts: another intent keeps the first company", () => {
    expect(cmd("apple microsoft news")).toBe("AAPL N");
  });
});

describe("typos", () => {
  it("'did you mean' only when a name is a letter or two away", () => {
    expect(cmd("mircosoft stock")).toBe("choices MSFT GP");
    expect(cmd("mircosoft 5 years")).toBe("choices MSFT GP 5Y");
    expect(cmd("nvidai stock")).toBe("choices NVDA GP");
    expect(cmd("appl stock price")).toBe("choices AAPL GP | APLE GP"); // both are 'apple' companies, one letter off
    expect(cmd("xyzzy blorp")).toBe("none");
    expect(cmd("zzzqqq")).toBe("none");
  });
  it("closestCompanies strict mode: nothing close = nothing, never the biggest names", () => {
    expect(closestCompanies("mircosoft", UNI, 3, { strict: true }).map((h) => h.symbol)).toEqual(["MSFT"]);
    expect(closestCompanies("zzzzqq", UNI, 3, { strict: true })).toEqual([]);
    expect(closestCompanies("zzzzqq", UNI, 2).length).toBe(2); // the old mode still falls back to big names
  });
  it("two share classes of one company are one suggestion", () => {
    expect(closestCompanies("alphabt", UNI, 5, { strict: true }).map((h) => h.symbol)).toHaveLength(1);
  });
  it("editDistance counts a swap of neighbours as one", () => {
    expect(editDistance("mircosoft", "microsoft", 2)).toBe(1);
    expect(editDistance("appl", "apple", 2)).toBe(1);
    expect(editDistance("abc", "xyz", 1)).toBe(2); // gave up: more than max
  });
});

describe("Yahoo name search fallback (nlRemote.pickRemote, the pure half)", () => {
  const hit = (symbol: string, name: string) => ({ symbol, name, via: "name" as const });
  it("one hit whose words match is the answer, with the command template filled in", () => {
    const r = pickRemote("bajaj finserv", [hit("BAJAJFINSV.NS", "Bajaj Finserv Limited"), hit("BAJAJ-AUTO.NS", "Bajaj Auto Limited")], "{S} GP 5Y");
    expect(r).toMatchObject({ kind: "command", command: "BAJAJFINSV.NS GP 5Y" });
  });
  it("fuzzy junk is dropped: every typed word must start a word of the name", () => {
    expect(pickRemote("xyzzy blorp", [hit("XYZ", "Block Inc")], "{S}")).toBeNull();
    expect(pickRemote("zomato", [], "{S}")).toBeNull();
  });
  it("several different names are choices, not a guess", () => {
    const r = pickRemote("tata", [hit("TATAMOTORS.NS", "Tata Motors Limited"), hit("TATASTEEL.NS", "Tata Steel Limited"), hit("TCS.NS", "Tata Consultancy Services")], "{S} GP");
    expect(r?.kind).toBe("choices");
  });
  it("the search is only asked for when nothing local knew the name", () => {
    const r = interpretNatural("zomato stock 5 years", ctx);
    expect(r).toEqual({ kind: "none", lookup: { phrase: "zomato", template: "{S} GP 5Y" } });
    expect(interpretNatural("apple stock", ctx).kind).toBe("command"); // known locally: no lookup
    expect(interpretNatural("gold price", ctx).kind).toBe("command"); // known by alias: no lookup
    expect(interpretNatural("xyzzy blorp", ctx)).toMatchObject({ kind: "none", lookup: { phrase: "xyzzy blorp" } });
  });
  it("no lookup before the company list is loaded or for filler-only text", () => {
    expect(interpretNatural("zomato stock", { ...ctx, companies: null })).toEqual({ kind: "none" });
    expect(interpretNatural("the", ctx)).toEqual({ kind: "none" });
  });
});

describe("speed", () => {
  it("indexes the company list once: 200 phrases over 8,000 companies stay far under v1's 7-28 ms each", () => {
    const big: UniverseEntry[] = [...UNI];
    for (let i = 0; i < 8000; i++) big.push(U(`Z${i}`, `Zork${i % 500} Holdings ${["Alpha", "Beta", "Gamma", "Delta"][i % 4]} Inc. Common Stock`, 1e6 + i));
    const bigCtx: NlContext = { ...ctx, companies: big };
    const phrases = ["apple stock price past 5 years", "how has apple done over 5 years", "bank of america news", "zork17 holdings alpha chart", "microsoft vs nvidia 3 years", "mircosoft stock", "tell me about the weather", "apple microsoft nvidia 1 year"];
    routeNatural(phrases[0], bigCtx); // builds the index (and is not timed)
    const t0 = performance.now();
    for (let i = 0; i < 200; i++) routeNatural(phrases[i % phrases.length], bigCtx);
    const perPhrase = (performance.now() - t0) / 200;
    expect(perPhrase).toBeLessThan(10); // measured: well under 1 ms; the bound only catches a return of the per-phrase full scan
  });
});
