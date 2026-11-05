import { describe, expect, it } from "vitest";
import { depthLimitFromError, intervalFits, limitText, longestRangeWithin, parseGpArgs, serializeGp, withInterval } from "./gpArgs";

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
