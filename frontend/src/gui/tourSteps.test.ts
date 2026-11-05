import { describe, expect, it } from "vitest";
import { TOUR_STEPS, tourText } from "./tourSteps";

describe("GUI tour steps", () => {
  it("has a handful of steps, each with a title, text and at least one selector", () => {
    expect(TOUR_STEPS.length).toBeGreaterThanOrEqual(3);
    expect(TOUR_STEPS.length).toBeLessThanOrEqual(6);
    for (const s of TOUR_STEPS) {
      expect(s.title).not.toBe("");
      expect(s.text).not.toBe("");
      expect(s.selectors.length).toBeGreaterThan(0);
    }
  });

  it("covers the menu bar, sidebar, command line, mode switch and the panel help button", () => {
    const all = TOUR_STEPS.flatMap((s) => s.selectors).join(" ");
    for (const part of ["gui-menubar", "gui-sidebar", "#cmdline", "mode-toggle", "pt-help"]) expect(all).toContain(part);
  });

  it("reads the live key names: a rebinding shows in the text, no chord left behind", () => {
    const mode = TOUR_STEPS.find((x) => x.text.includes("{toggleMode}"))!;
    expect(tourText(mode, { toggleMode: ["Alt+M"] })).toContain("(Alt+M)");
    expect(tourText(mode, { toggleMode: [] })).toContain("(no key bound)");
    for (const x of TOUR_STEPS) expect(tourText(x, { toggleMode: ["A"], helpDrawer: ["B"] })).not.toMatch(/[{}]|Alt\+[GH]/);
  });
});
