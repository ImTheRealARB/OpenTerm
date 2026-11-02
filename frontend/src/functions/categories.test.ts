import { describe, expect, it } from "vitest";
import { CATEGORIES, CATEGORY_OF, categoryOf, groupByCategory } from "./categories";
import { FUNCTION_LIST } from "./registry";

describe("GUI categories", () => {
  it("has the seven menu headings, in menu order", () => {
    expect([...CATEGORIES]).toEqual(["Markets", "Charts", "News", "Research", "Portfolio", "Backtest", "Settings"]);
  });

  it("gives every registered function a category", () => {
    const missing = FUNCTION_LIST.map((f) => f.code).filter((c) => !CATEGORY_OF[c]);
    expect(missing).toEqual([]);
  });

  it("maps no code that is not in the registry (no stale entries)", () => {
    const codes = new Set(FUNCTION_LIST.map((f) => f.code));
    expect(Object.keys(CATEGORY_OF).filter((c) => !codes.has(c))).toEqual([]);
  });

  it("only uses known categories", () => {
    for (const c of Object.values(CATEGORY_OF)) expect(CATEGORIES).toContain(c);
  });

  it("puts the utilities under Settings and the AI functions under Research", () => {
    for (const c of ["HELP", "PERF", "SHORTCUTS", "APIKEYS", "SOURCES", "LOG"]) expect(categoryOf(c)).toBe("Settings");
    for (const c of ["AI", "SWARM", "THESIS", "AUDIT"]) expect(categoryOf(c)).toBe("Research");
  });

  it("groupByCategory covers every function exactly once", () => {
    const groups = groupByCategory(FUNCTION_LIST);
    expect(groups.map((g) => g.category)).toEqual([...CATEGORIES]);
    const all = groups.flatMap((g) => g.items.map((f) => f.code));
    expect(all.length).toBe(FUNCTION_LIST.length);
    expect(new Set(all).size).toBe(FUNCTION_LIST.length);
  });

  it("categoryOf throws loudly for an unknown code", () => {
    expect(() => categoryOf("NOPE")).toThrow(/NOPE/);
  });
});
