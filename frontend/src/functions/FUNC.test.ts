import { describe, expect, it } from "vitest";
import { ALIASES } from "./aliases";
import { buildRows, filterRows, shortPurpose, type DirEntry } from "./funcDirectory";
import { FUNCTIONS, FUNCTION_LIST } from "./registry";

const list: DirEntry[] = [
  { code: "GP", title: "Price chart", needsSecurity: true },
  { code: "FXC", title: "Currency cross matrix", needsSecurity: false },
  { code: "FA", title: "Financial analysis (statements: IS BS CF)", needsSecurity: true },
  { code: "NEW", title: "Future thing", needsSecurity: false },
];

describe("function directory", () => {
  it("shortens a title to its first clause", () => {
    expect(shortPurpose("Financial analysis (statements)")).toBe("FINANCIAL ANALYSIS");
    expect(shortPurpose("Options: IV and Greeks")).toBe("OPTIONS");
    expect(shortPurpose("Price chart")).toBe("PRICE CHART");
  });
  it("builds sorted rows with aliases", () => {
    const rows = buildRows(list, { WCRS: "FXC", BAD: "NOPE" }, (c) => (c === "GP" ? "Charts" : undefined));
    expect(rows.map((r) => r.code)).toEqual(["FA", "FXC", "GP", "NEW", "WCRS"]); // BAD points nowhere: dropped
    expect(rows.find((r) => r.code === "WCRS")).toMatchObject({ aliasOf: "FXC", purpose: "SAME AS FXC: CURRENCY CROSS MATRIX" });
    expect(rows.find((r) => r.code === "GP")).toMatchObject({ takes: "SEC", category: "Charts" });
  });
  it("filters: code prefix first, then contains", () => {
    const rows = buildRows(list, {}, () => undefined);
    expect(filterRows(rows, "").length).toBe(4);
    expect(filterRows(rows, "f").map((r) => r.code)).toEqual(["FA", "FXC", "NEW"]); // FA, FXC start with F; NEW has "FUTURE"
    expect(filterRows(rows, "cross").map((r) => r.code)).toEqual(["FXC"]);
    expect(filterRows(rows, "zzz")).toEqual([]);
  });
  it("is registered with a loader", () => {
    expect(FUNCTIONS.get("FUNC")?.load).toBeTypeOf("function");
  });
});

describe("aliases", () => {
  it("point at real functions and are not codes themselves", () => {
    const codes = new Set(FUNCTION_LIST.map((f) => f.code));
    for (const [alias, target] of Object.entries(ALIASES)) {
      expect(codes.has(target), `${alias} -> ${target}`).toBe(true);
      expect(codes.has(alias), `${alias} is also a real code`).toBe(false);
    }
  });
  it("resolve through the registry to the canonical definition", () => {
    expect(FUNCTIONS.get("WCRS")).toBe(FUNCTIONS.get("FXC"));
    expect(FUNCTIONS.get("WCRS")?.code).toBe("FXC");
    expect(FUNCTIONS.get("MENU")?.code).toBe("FUNC");
  });
});
