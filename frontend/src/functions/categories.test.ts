import { describe, expect, it } from "vitest";
import { TWINS } from "./aliases";
import { CATEGORIES, CATEGORY_OF, MENU, categoryOf, flyoutPosition, menuOf } from "./categories";
import { FUNCTION_LIST } from "./registry";

const placed = CATEGORIES.flatMap((c) => MENU[c].flatMap((g) => g.codes));

describe("GUI categories", () => {
  it("has the seven menu headings, in menu order", () => {
    expect([...CATEGORIES]).toEqual(["Markets", "Charts", "News", "Research", "Portfolio", "Backtest", "Settings"]);
  });

  it("places every registered function in exactly one subgroup, or lists it as a twin", () => {
    const codes = FUNCTION_LIST.map((f) => f.code);
    expect(codes.filter((c) => !placed.includes(c) && !TWINS[c])).toEqual([]);
    expect(placed.length).toBe(new Set(placed).size); // no code in two subgroups
    for (const a of Object.keys(TWINS)) expect(placed).not.toContain(a); // a twin is never listed itself
  });

  it("has no stale codes (menu entries and twins all exist in the registry)", () => {
    const codes = new Set(FUNCTION_LIST.map((f) => f.code));
    expect(placed.filter((c) => !codes.has(c))).toEqual([]);
    expect(Object.entries(TWINS).flat().filter((c) => !codes.has(c))).toEqual([]);
  });

  it("keeps menus short: at most 8 subgroups per category, at most 12 functions per subgroup, no empty subgroup", () => {
    for (const c of CATEGORIES) {
      expect(MENU[c].length).toBeLessThanOrEqual(8);
      for (const g of MENU[c]) {
        expect(g.codes.length, `${c} > ${g.name}`).toBeGreaterThan(0);
        expect(g.codes.length, `${c} > ${g.name}`).toBeLessThanOrEqual(12);
      }
    }
  });

  it("gives every registered function a category (twins share their original's)", () => {
    expect(FUNCTION_LIST.map((f) => f.code).filter((c) => !CATEGORY_OF[c])).toEqual([]);
    expect(categoryOf("SEC")).toBe(categoryOf("FIL"));
    expect(categoryOf("MONITOR")).toBe("Settings");
  });

  it("puts the utilities under Settings and the AI functions under Research", () => {
    for (const c of ["HELP", "PERF", "SHORTCUTS", "APIKEYS", "SOURCES", "LOG"]) expect(categoryOf(c)).toBe("Settings");
    for (const c of ["AI", "SWARM", "THESIS", "AUDIT"]) expect(categoryOf(c)).toBe("Research");
  });

  it("menuOf lists a category's subgroups with their functions in menu order", () => {
    const m = menuOf("Markets", FUNCTION_LIST);
    expect(m.map((g) => g.name)).toEqual(MENU.Markets.map((g) => g.name));
    expect(m.find((g) => g.name === "Crypto")!.items.map((f) => f.code)).toEqual([...MENU.Markets.find((g) => g.name === "Crypto")!.codes]);
    // Every non-twin function shows up in exactly one menu.
    const shown = CATEGORIES.flatMap((c) => menuOf(c, FUNCTION_LIST).flatMap((g) => g.items.map((f) => f.code)));
    expect(shown.length).toBe(FUNCTION_LIST.length - Object.keys(TWINS).length);
  });

  it("categoryOf throws loudly for an unknown code", () => {
    expect(() => categoryOf("NOPE")).toThrow(/NOPE/);
  });
});

describe("flyoutPosition", () => {
  const vp = { width: 1280, height: 800 };
  const size = { width: 300, height: 200 };

  it("opens to the right of the row, level with it", () => {
    expect(flyoutPosition({ top: 100, left: 200, right: 500 }, size, vp)).toEqual({ top: 100, left: 500, flipped: false });
  });

  it("flips to the left when the right side would cross the window edge", () => {
    expect(flyoutPosition({ top: 100, left: 900, right: 1100 }, size, vp)).toEqual({ top: 100, left: 600, flipped: true });
  });

  it("stays right when there is no room on the left either", () => {
    expect(flyoutPosition({ top: 0, left: 100, right: 1100 }, size, vp).flipped).toBe(false);
  });

  it("moves up so a flyout near the bottom stays on screen", () => {
    expect(flyoutPosition({ top: 700, left: 0, right: 200 }, size, vp).top).toBe(600);
    expect(flyoutPosition({ top: 700, left: 0, right: 200 }, { width: 300, height: 900 }, vp).top).toBe(0);
  });
});
