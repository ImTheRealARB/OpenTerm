import { describe, expect, it } from "vitest";
import { FUNCTIONS, isFunction } from "../functions/registry";
import { parseLayout, snapshot } from "../state/layoutState";
import { starterWorkspace } from "./starterLayout";
import { TEMPLATE_INFO } from "./templateMenu";
import { TEMPLATES, isReplaceable, templateById, templateWorkspace } from "./templates";

describe("workspace templates", () => {
  it("has the four templates", () => {
    expect(TEMPLATES.map((t) => t.id)).toEqual(["LONGTERM", "DAY", "MACRO", "INDIA"]);
  });
  it("matches the GUI menu list", () => {
    expect(TEMPLATE_INFO).toEqual(TEMPLATES.map((t) => ({ id: t.id, label: t.label })));
  });
  it("uses only registered, built functions", () => {
    for (const t of TEMPLATES) for (const v of t.views) expect(FUNCTIONS.get(v.fn!)?.load, `${t.id} ${v.fn}`).toBeTypeOf("function");
  });
  it("every function that needs a security has one", () => {
    for (const t of TEMPLATES) for (const v of t.views) if (FUNCTIONS.get(v.fn!)?.needsSecurity) expect(v.security?.symbol, `${t.id} ${v.fn}`).toBeTruthy();
  });
  it("builds a layout that the saved-layout validator accepts, one leaf per panel", () => {
    for (const t of TEMPLATES) {
      const back = parseLayout(snapshot(templateWorkspace(t)), isFunction);
      expect(back, t.id).not.toBeNull();
      expect(Object.keys(back!.panels)).toHaveLength(t.views.length);
      expect(back!.panels[1].views[0].fn).toBe(t.views[0].fn);
    }
  });
  it("Day trader has GP 5MIN, a watch list, MOV and news", () => {
    expect(templateWorkspace(templateById("day")!).panels[1].views[0]).toMatchObject({ fn: "GP", args: ["1D", "5MIN"] });
    expect(templateById("DAY")!.views.map((v) => v.fn)).toEqual(["GP", "Q", "MOV", "N"]);
  });
  it("finds templates by id or alias, case-insensitive", () => {
    expect(templateById("macro")?.id).toBe("MACRO");
    expect(templateById("long-term")?.id).toBe("LONGTERM");
    expect(templateById("nifty")?.id).toBe("INDIA");
    expect(templateById("nope")).toBeUndefined();
  });
  it("replaceable only for the starter layout or a lone help panel", () => {
    expect(isReplaceable(starterWorkspace())).toBe(true);
    expect(isReplaceable({ layout: { t: "leaf", id: 1 }, panels: { 1: { id: 1, views: [{ fn: "HELP", args: [] }], pos: 0 } }, focus: 1, maximized: null })).toBe(true);
    expect(isReplaceable(templateWorkspace(TEMPLATES[0]))).toBe(false);
    const t = starterWorkspace();
    const q = t.panels[1].views[0];
    t.panels[1] = { id: 1, views: [q, { fn: "TMPL", args: ["DAY"] }], pos: 1 };
    expect(isReplaceable(t)).toBe(true); // the TMPL panel itself is not a change
    const s = starterWorkspace();
    s.panels[2].views[0] = { fn: "GP", security: { symbol: "TSLA" }, args: [] };
    expect(isReplaceable(s)).toBe(false);
  });
});
