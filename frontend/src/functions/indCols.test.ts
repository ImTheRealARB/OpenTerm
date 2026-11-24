import { describe, expect, it } from "vitest";
import { cellText, colsNote, holds, indColumns, splitCols, typedCols } from "./indCols";
import { parseWl } from "../command/watchlistArgs";

describe("indicator columns", () => {
  it("splits COLS= off the args (last one wins)", () => {
    expect(splitCols(["AAPL", "cols=rsi14", "MSFT"])).toEqual({ args: ["AAPL", "MSFT"], cols: "RSI14" });
    expect(splitCols(["AAPL"])).toEqual({ args: ["AAPL"], cols: null });
    expect(splitCols(["COLS=A", "COLS=B"]).cols).toBe("B");
  });

  it("reads the typed columns with the labels the server will use", () => {
    expect(typedCols("RSI14<30,REL_VOL,PCT_SMA200")).toEqual([
      { label: "RSI14", op: "<", num: 30 },
      { label: "REL_VOL20", op: null, num: null },
      { label: "PCT_SMA200", op: null, num: null },
    ]);
  });

  it("colours a cell only when its comparison holds", () => {
    const c = { label: "RSI14", op: "<" as const, num: 30 };
    expect(holds(c, 25)).toBe(true);
    expect(holds(c, 35)).toBe(false);
    expect(holds(c, null)).toBe(false);
    expect(holds({ label: "X", op: null, num: null }, 1)).toBe(false);
    const res = { cols: [c], rows: { AAPL: { date: "2026-11-20", values: { RSI14: 25 }, note: "" } }, labels: { fixtures: "RECORDED FIXTURE DATA" } };
    const [col] = indColumns<{ symbol: string }>(res, "RSI14<30");
    expect(col.title).toBe("RSI14<30");
    expect(col.text({ symbol: "AAPL" })).toBe("25.00");
    expect(col.color?.({ symbol: "AAPL" })).toBe("up");
    expect(col.text({ symbol: "MSFT" })).toBe("—");
    expect(colsNote("RSI14<30", { error: null, done: 0, total: 0, res })).toBe("COLS: NEWEST DAILY BAR (TO 2026-11-20) · RECORDED FIXTURE DATA");
  });

  it("formats percent, return and volume columns", () => {
    expect(cellText("PCT_SMA200", 3.21)).toBe("+3.2%");
    expect(cellText("RET20", -0.05)).toBe("-5.0%");
    expect(cellText("REL_VOL20", 1.5)).toBe("1.50x");
    expect(cellText("ATR14", null)).toBe("—");
  });

  it("WL NAME COLS= opens the list", () => {
    expect(parseWl(["TECH", "COLS=RSI14"])).toEqual({ kind: "view", name: "TECH" });
  });
});
