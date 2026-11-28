import { describe, expect, it } from "vitest";
import { MAX_SCRIPTS, depthLimitFromError, intervalFits, intervalToken, limitText, longestRangeWithin, parseGpArgs, parseScriptToken, serializeGp, serializeScripts, withInterval } from "./gpArgs";

describe("candle-length limits (reported by the backend per symbol)", () => {
  const yahoo = { "1m": 7, "5m": 60, "15m": 60, "60m": 730 };
  const deep = { "1m": 1400, "5m": 1400, "15m": 1400, "60m": 1400 };
  it("minute candles only fit ranges inside the reported depth; daily and longer always fit", () => {
    expect(intervalFits("5D", "5m", yahoo)).toBe(true);
    expect(intervalFits("1M", "15m", yahoo)).toBe(true);
    expect(intervalFits("1Y", "15m", yahoo)).toBe(false);
    expect(intervalFits("MAX", "1d", yahoo)).toBe(true);
    expect(intervalFits("1Y", "60m", yahoo)).toBe(true);
    expect(intervalFits("2Y", "60m", yahoo)).toBe(false);
  });
  it("a deeper source (for example Kite for Indian shares) allows what Yahoo would not", () => {
    expect(intervalFits("1Y", "5m", deep)).toBe(true);
    expect(intervalFits("5Y", "5m", deep)).toBe(false);
  });
  it("offers everything while the limits are not known yet", () => {
    expect(intervalFits("MAX", "1m", undefined)).toBe(true);
  });
  it("understands the typed words as well as the tokens", () => {
    expect(intervalFits("1Y", "15min", yahoo)).toBe(false);
    expect(intervalFits("5D", "1MIN", yahoo)).toBe(true);
    expect(intervalFits("1M", "1MIN", yahoo)).toBe(false);
  });
  it("knows the Phase 21 lengths, ties hours to the 60m reach, and never mistakes them for a range", () => {
    expect(["4H", "Q", "yearly", "2wk", "1sec"].map(intervalToken)).toEqual(["4h", "3mo", "12mo", "2wk", "1s"]);
    expect(intervalFits("1Y", "4h", yahoo)).toBe(true); // the server reports 4h with the reach of 60m
    expect(intervalFits("2Y", "4h", { ...yahoo, "4h": 730 })).toBe(false);
    expect(parseGpArgs(["1Y", "4H"])).toMatchObject({ range: "1Y", interval: "4H" });
    expect(parseGpArgs(["3M", "3mo"])).toMatchObject({ range: "3M", interval: "3mo" }); // 3M is the range, 3mo the quarterly candle
    expect(parseGpArgs(["VS", "MSFT", "Q"])).toMatchObject({ compare: ["MSFT"], interval: "Q" }); // VS stops at an interval word
  });
  it("names the longest range that fits and words the depth", () => {
    expect(longestRangeWithin(7)).toBe("5D");
    expect(longestRangeWithin(60)).toBe("1M");
    expect(longestRangeWithin(730)).toBe("1Y");
    expect(longestRangeWithin(0)).toBeNull();
    expect(limitText(60)).toBe("up to 60 days");
    expect(limitText(300)).toBe("up to 10 months");
    expect(limitText(1400)).toBe("up to 3.8 years");
    expect(limitText(730)).toBe("up to 2 years");
  });
  it("reads the depth out of the server's message, and only that message", () => {
    expect(depthLimitFromError("INTERVAL 5m ONLY AVAILABLE FOR THE LAST 60 DAYS (AAPL 1Y).")).toBe(60);
    expect(depthLimitFromError("NO DATA FOR SYMBOL")).toBeNull();
  });
});

describe("GP arguments", () => {
  it("keeps the old forms working", () => {
    expect(parseGpArgs([])).toMatchObject({ range: "1Y", type: "CANDLE", log: false, compare: [], pane: false, evt: false, indicators: [] });
    const p = parseGpArgs(["5Y", "W", "VS", "spy", "LINE", "LOG", "SMA20", "RSI"]);
    expect(p).toMatchObject({ range: "5Y", interval: "W", compare: ["SPY"], type: "LINE", log: true, indicators: ["SMA20", "RSI"] });
    expect(parseGpArgs(["5min"]).interval).toBe("5min");
  });

  it("VS takes up to three symbols and stops at a keyword", () => {
    expect(parseGpArgs(["VS", "MSFT", "NVDA", "AMD", "TSLA"]).compare).toEqual(["MSFT", "NVDA", "AMD"]);
    const p = parseGpArgs(["VS", "MSFT", "NVDA", "PANE", "1Y", "RSI"]);
    expect(p).toMatchObject({ compare: ["MSFT", "NVDA"], pane: true, range: "1Y", indicators: ["RSI"] });
    expect(parseGpArgs(["VS", "MSFT", "D"]).compare).toEqual(["MSFT"]);
    expect(parseGpArgs(["VS", "MSFT", "D"]).interval).toBe("D");
    expect(parseGpArgs(["VS", "MSFT", "MSFT"]).compare).toEqual(["MSFT"]);
  });

  it("EVT and the Phase 19 studies and pattern tokens", () => {
    const p = parseGpArgs(["EVT", "ATR", "PAT:CANDLE", "PAT:SMC", "PAT:ICHI", "ICHIMOKU", "atr"]);
    expect(p.evt).toBe(true);
    expect(p.indicators).toEqual(["ATR", "PAT:CANDLE", "PAT:SMC", "ICHIMOKU"]);
  });

  it("serialize then parse gives the same thing", () => {
    const p = parseGpArgs(["2Y", "W", "VS", "A", "B", "PANE", "EVT", "OHLC", "LOG", "SUPERTREND", "PSAR"]);
    expect(parseGpArgs(serializeGp(p))).toEqual(p);
    expect(serializeGp(parseGpArgs([]))).toEqual(["1Y"]);
  });

  it("library indicators and formulas are single tokens that survive serialize and parse", () => {
    const p = parseGpArgs(["ATR(14)", "LIB:CMF", "bb(20,2)", "F:EMA(close,12)-EMA(close,26)", "F:close%20%3E%20open", "ATR(14)", "RSI"]);
    expect(p.indicators).toEqual(["RSI"]);
    expect(p.custom.map((c) => c.key)).toEqual(["LIB:ATR:14", "LIB:CMF", "LIB:BB:20:2", "F:EMA(close%2C12)-EMA(close%2C26)", "F:close%20%3E%20open"]);
    expect(p.custom[3].formula).toBe("EMA(close,12)-EMA(close,26)");
    expect(p.custom[1]).toMatchObject({ id: "CMF", params: undefined });
    expect(parseGpArgs(serializeGp(p))).toEqual(p);
    expect(serializeGp(p).slice(-5)).toEqual(["ATR(14)", "LIB:CMF", "BB(20,2)", "F:EMA(close%2C12)-EMA(close%2C26)", "F:close%20%3E%20open"]);
  });

  it("junk tokens are ignored and VS stops at a library token", () => {
    expect(parseGpArgs(["ATR(x)", "F:", "F:%E0%A4%A", "LIB:"]).custom).toEqual([]);
    const p = parseGpArgs(["VS", "MSFT", "ATR(14)"]);
    expect(p.compare).toEqual(["MSFT"]);
    expect(p.custom).toHaveLength(1);
  });
});

describe("withInterval (GUI candle-length dropdown)", () => {
  const d = { range: "1Y", type: "CANDLE" as const };
  it("sets the interval and keeps range and indicators", () => {
    expect(withInterval(["5D", "RSI"], "15m", d)).toEqual(["5D", "15m", "RSI"]);
  });
  it("replaces an existing interval", () => {
    expect(withInterval(["5D", "5m"], "1d", d)).toEqual(["5D", "1d"]);
  });
  it("empty token goes back to Auto", () => {
    expect(withInterval(["5D", "5m"], "", d)).toEqual(["5D"]);
  });
});

describe("REPLAY practice exits (STOP= TARGET=)", () => {
  it("reads percent exits, keeps them in the saved args, and ignores values out of range", () => {
    const p = parseGpArgs(["REPLAY", "2024-03-01", "STOP=5", "target=12.5"]);
    expect(p.replay).toEqual({ start: "2024-03-01" });
    expect(p.exits).toEqual({ stop: 5, target: 12.5 });
    expect(serializeGp(p, "CANDLE")).toEqual(expect.arrayContaining(["REPLAY", "2024-03-01", "STOP=5", "TARGET=12.5"]));
    expect(parseGpArgs(["REPLAY", "STOP=0"]).exits).toBeUndefined();
    expect(parseGpArgs(["REPLAY", "STOP=100"]).exits).toBeUndefined();
    expect(parseGpArgs(["REPLAY", "STOP=abc"]).exits).toBeUndefined();
  });
});

describe("SCRIPT= (OpenTerm Script on a chart)", () => {
  it("reads one script, several, and per-chart inputs in order", () => {
    expect(parseGpArgs(["1Y", "SCRIPT=rsi_bands"]).scripts).toEqual([{ name: "RSI_BANDS", inputs: [] }]);
    expect(parseGpArgs(["SCRIPT=A,B"]).scripts.map((s) => s.name)).toEqual(["A", "B"]);
    expect(parseGpArgs(["SCRIPT=RSI_BANDS(14,70)"]).scripts).toEqual([{ name: "RSI_BANDS", inputs: ["14", "70"] }]);
    // an empty slot keeps the script's default; trailing empties are dropped
    expect(parseGpArgs(["SCRIPT=A(,70,),B"]).scripts).toEqual([{ name: "A", inputs: ["", "70"] }, { name: "B", inputs: [] }]);
  });

  it("keeps the other args working and does not treat SCRIPT= as a compare symbol", () => {
    const p = parseGpArgs(["VS", "MSFT", "SCRIPT=A(3)", "RSI", "ATR(14)", "5Y"]);
    expect(p.compare).toEqual(["MSFT"]);
    expect(p.scripts).toEqual([{ name: "A", inputs: ["3"] }]);
    expect(p.indicators).toEqual(["RSI"]);
    expect(p.custom.map((c) => c.key)).toEqual(["LIB:ATR:14"]);
    expect(p.range).toBe("5Y");
  });

  it("round-trips through serializeGp as ONE token with no spaces", () => {
    const args = ["1Y", "RSI", "SCRIPT=RSI_BANDS(14,,x%20y),OTHER"];
    const p = parseGpArgs(args);
    expect(p.scripts[0].inputs).toEqual(["14", "", "x y"]);
    const out = serializeGp(p);
    const tok = out.filter((a) => a.startsWith("SCRIPT="));
    expect(tok).toEqual(["SCRIPT=RSI_BANDS(14,,x%20y),OTHER"]);
    expect(parseGpArgs(out)).toEqual(p);
  });

  it("encodes the characters that would break the token", () => {
    const list = [{ name: "A", inputs: ["a,b", "(c)", "100%"] }];
    const tok = serializeScripts(list);
    expect(tok).not.toMatch(/\s/);
    expect(parseScriptToken(tok)).toEqual(list);
  });

  it("ignores a malformed SCRIPT= whole, dedupes names and caps the count", () => {
    expect(parseGpArgs(["SCRIPT="]).scripts).toEqual([]);
    expect(parseGpArgs(["SCRIPT=a b"]).scripts).toEqual([]);
    expect(parseGpArgs(["SCRIPT=A,,B"]).scripts).toEqual([]);
    expect(parseGpArgs(["SCRIPT=BAD%ZZ(%ZZ)"]).scripts).toEqual([]);
    expect(parseGpArgs(["SCRIPT=A(1),A(2)"]).scripts).toEqual([{ name: "A", inputs: ["1"] }]);
    const many = Array.from({ length: MAX_SCRIPTS + 3 }, (_, i) => `S${i}`).join(",");
    expect(parseGpArgs([`SCRIPT=${many}`]).scripts).toHaveLength(MAX_SCRIPTS);
  });

  it("a chart with no script serializes exactly as before", () => {
    expect(serializeGp(parseGpArgs(["1Y", "RSI"]))).toEqual(["1Y", "RSI"]);
  });
});
