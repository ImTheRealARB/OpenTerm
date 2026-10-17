import { describe, expect, it } from "vitest";
import { cellColor, cellText, gridColumns, keyValueArgs, type TableColumn, type TableSection } from "./tablePayload";

describe("cellText", () => {
  it("prints null as a dash and never invents a value", () => {
    for (const k of ["text", "int", "num", "pct", "money", "price", "date"] as const) expect(cellText(k, null)).toBe("—");
    expect(cellText("num", Number.NaN)).toBe("—");
    expect(cellText("num", "abc")).toBe("—");
  });
  it("formats each kind", () => {
    expect(cellText("int", 9375000)).toBe("9,375,000");
    expect(cellText("num", 1.97842)).toBe("1.98");
    expect(cellText("price", 360)).toBe("360.00");
    expect(cellText("price", 0.0512)).toBe("0.0512");
    expect(cellText("money", 113626875100)).toBe("113.63B");
    expect(cellText("money", 16759518)).toBe("16.76M");
    expect(cellText("pct", 0.0452)).toBe("+4.52%");
    expect(cellText("pct", -0.041)).toBe("-4.10%");
    expect(cellText("date", "2026-10-12")).toBe("2026-10-12");
  });
});

describe("cellColor", () => {
  const growth: TableColumn = { key: "growth", title: "GROWTH", kind: "pct", align: "right" };
  const weight: TableColumn = { key: "weight", title: "WEIGHT", kind: "pct", align: "right" };
  it("colours only change-like columns", () => {
    expect(cellColor(growth, 0.07)).toBe("up");
    expect(cellColor(growth, -0.07)).toBe("down");
    expect(cellColor(weight, 0.07)).toBe("fg");
    expect(cellColor({ key: "d", title: "D", kind: "date", align: "left" }, "2026-01-01")).toBe("dim");
  });
});

describe("gridColumns", () => {
  const s: TableSection = {
    id: "eps",
    title: "EPS",
    note: null,
    columns: [
      { key: "period", title: "PERIOD", kind: "text", align: "left" },
      { key: "avg", title: "AVG", kind: "num", align: "right" },
    ],
    rows: [{ period: "CURRENT QUARTER ESTIMATE", avg: 1.97842 }],
  };
  it("sizes columns from the widest cell and keeps the first text column accented", () => {
    const cols = gridColumns(s);
    expect(cols[0].width).toBe("CURRENT QUARTER ESTIMATE".length);
    expect(cols[1].text(s.rows[0])).toBe("1.98");
    expect(cols[0].color!(s.rows[0])).toBe("acc");
  });
});

describe("keyValueArgs", () => {
  it("splits KEY=VALUE and reports the rest", () => {
    expect(keyValueArgs(["ERP=5.5", "g=2.5", "oops", "=3", "x="])).toEqual({ params: { erp: "5.5", g: "2.5" }, bad: ["oops", "=3", "x="] });
  });
});
