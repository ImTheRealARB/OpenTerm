import { describe, expect, it } from "vitest";
import type { PanelState } from "../state/workspace";
import { menuItems, menuKey, viewLabel, type FnInfo, type MenuState } from "./windowMenu";

// The real lists come from the registry's `related` ranks; the test supplies the same shape.
const info: FnInfo = {
  isBuilt: (c) => c !== "OMON",
  title: (c) => `${c} title`,
  related: (withSecurity) => (withSecurity ? ["DES", "GP", "QR", "OMON"] : ["WEI", "MOV", "FX"]),
};
const panel: PanelState = {
  id: 1,
  pos: 1,
  views: [{ fn: "WEI", args: [] }, { fn: "GP", security: { symbol: "AAPL" }, args: ["1Y"] }, { fn: "DES", security: { symbol: "AAPL" }, args: [] }],
};

describe("window menu items", () => {
  it("RECENT lists history newest first and marks the current view", () => {
    const items = menuItems(0, panel, info);
    expect(items.map((i) => i.label)).toEqual(["AAPL DES", "AAPL GP 1Y", "WEI"]);
    expect(items.map((i) => i.kind === "history" && i.current)).toEqual([false, true, false]);
  });

  it("RELATED offers built security functions, minus the current one", () => {
    const fns = menuItems(1, panel, info).map((i) => (i.kind === "fn" ? i.fn : ""));
    expect(fns[0]).toBe("DES");
    expect(fns).not.toContain("GP");
    expect(fns).not.toContain("OMON");
  });

  it("RELATED falls back to market functions without a security", () => {
    const fns = menuItems(1, { ...panel, pos: 0 }, info).map((i) => (i.kind === "fn" ? i.fn : ""));
    expect(fns[0]).toBe("MOV");
    expect(fns).not.toContain("WEI");
  });

  it("OPTIONS lists the panel actions", () => {
    expect(menuItems(2, panel, info).map((i) => (i.kind === "action" ? i.action : ""))).toEqual([
      "maximize", "splitVertical", "splitHorizontal", "refresh", "exportCsv", "closePanel",
    ]);
  });

  it("labels an empty view", () => expect(viewLabel({ args: [] })).toBe("EMPTY"));
});

describe("window menu keys", () => {
  const s: MenuState = { panel: 1, menu: 0, sel: 0 };
  it("arrows wrap across menus and items", () => {
    expect(menuKey(s, "ArrowLeft", 3)?.state).toEqual({ panel: 1, menu: 2, sel: 0 });
    expect(menuKey({ ...s, sel: 2 }, "ArrowRight", 3)?.state).toEqual({ panel: 1, menu: 1, sel: 0 });
    expect(menuKey(s, "ArrowUp", 3)?.state?.sel).toBe(2);
    expect(menuKey({ ...s, sel: 2 }, "ArrowDown", 3)?.state?.sel).toBe(0);
  });
  it("Enter and digits pick and close; out-of-range digits do nothing", () => {
    expect(menuKey({ ...s, sel: 1 }, "Enter", 3)).toEqual({ state: null, pick: 1 });
    expect(menuKey(s, "3", 3)).toEqual({ state: null, pick: 2 });
    expect(menuKey(s, "4", 3)).toEqual({ state: s });
  });
  it("Escape closes; other keys are not the menu's", () => {
    expect(menuKey(s, "Escape", 3)).toEqual({ state: null });
    expect(menuKey(s, "x", 3)).toBeNull();
  });
});
