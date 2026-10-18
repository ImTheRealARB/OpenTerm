import { describe, expect, it } from "vitest";
import { parseGpArgs, serializeGp } from "./gpArgs";

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
});
