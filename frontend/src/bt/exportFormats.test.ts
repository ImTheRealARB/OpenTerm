import { describe, expect, it } from "vitest";
import { BT_EXPORTS, EXPORT_WORDS, exportFileName, rulesOnlyRefusal } from "./exportFormats";
import { buttonsFor } from "../gui/toolbars";

describe("BT export formats", () => {
  it("names files by format", () => {
    expect(exportFileName("abc", "pine")).toBe("BT_abc.pine");
    expect(exportFileName("abc", "MQL5")).toBe("BT_abc.mq5");
    expect(exportFileName("abc", "pdf")).toBe("BT_abc.pdf");
    expect(exportFileName("abc", "XLSX")).toBe("BT_abc.xlsx");
    expect(exportFileName("abc", "trades")).toBe("BT_abc_trades.csv");
  });

  it("only translations are rule-only; reports are binary", () => {
    expect(Object.entries(BT_EXPORTS).filter(([, f]) => f.rulesOnly).map(([w]) => w)).toEqual(["PINE", "MQL5"]);
    expect(BT_EXPORTS.PDF.binary && BT_EXPORTS.XLSX.binary && !BT_EXPORTS.MQL5.binary).toBe(true);
    expect(EXPORT_WORDS).toContain("MQL5|PDF|XLSX");
    expect(rulesOnlyRefusal("mql5")).toContain("MQL5 EXPORT NEEDS A RULE STRATEGY");
  });

  it("the BT toolbar has a button per export key", () => {
    const keys = buttonsFor("BT", ["SMA20>SMA50"]).map((b) => b.key);
    for (const k of ["p", "q", "d", "b"]) expect(keys).toContain(k);
  });
});
