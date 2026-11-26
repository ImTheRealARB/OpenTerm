import { describe, expect, it } from "vitest";
import { parseAlrt } from "../command/alertArgs";
import { gpStudies, parseMrrArgs, parseScanArgs } from "./scanArgs";

describe("SCAN / MRR / smart ALRT arguments (Phase 27)", () => {
  it("parses scans and saved scans", () => {
    expect(parseScanArgs(["SPX", "RSI14<30", "AND", "CLOSE>SMA200"])).toEqual({ ok: true, act: "scan", universe: "SPX", rule: "RSI14<30 AND CLOSE>SMA200" });
    expect(parseScanArgs(["SAVE", "dip", "spx", "RSI14<30", "DAILY=22:15"])).toEqual({ ok: true, act: "save", name: "DIP", universe: "SPX", rule: "RSI14<30", daily: "22:15" });
    expect(parseScanArgs(["SAVE", "dip", "spx", "RSI14<30", "DAILY=25:00"]).ok).toBe(false);
    expect(parseScanArgs([])).toEqual({ ok: true, act: "saved" });
  });

  it("parses MRR and maps rule terms to GP studies", () => {
    expect(parseMrrArgs(["spx", "1m"])).toEqual({ ok: true, universe: "SPX", period: "1M" });
    expect(parseMrrArgs(["SPX", "2W"]).ok).toBe(false);
    expect(gpStudies(["CLOSE", "SMA200", "RSI14", "SMA33"])).toEqual(["SMA200", "RSI"]);
  });

  it("reads indicator and drawing alerts in ALRT", () => {
    expect(parseAlrt(["AAPL", "RSI14<30"])).toEqual({ kind: "createInd", symbol: "AAPL", rule: "RSI14<30" });
    expect(parseAlrt(["AAPL", "SMA50", "CROSS>", "SMA200"])).toEqual({ kind: "createInd", symbol: "AAPL", rule: "SMA50 CROSS> SMA200" });
    expect(parseAlrt(["AAPL", "LINE", "2"])).toEqual({ kind: "createDraw", symbol: "AAPL", n: 2 });
    expect(parseAlrt(["DEL", "S0a1b2c3d"])).toEqual({ kind: "deleteSmart", id: "0a1b2c3d" });
    expect(parseAlrt(["AAPL", ">", "200"]).kind).toBe("create"); // price alerts unchanged
  });
});
