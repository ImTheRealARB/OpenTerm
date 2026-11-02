import { describe, expect, it } from "vitest";
import { TOUR_STEPS } from "./tourSteps";

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

  it("covers the menu bar, sidebar, symbol box, mode switch and the panel help button", () => {
    const all = TOUR_STEPS.flatMap((s) => s.selectors).join(" ");
    for (const part of ["gui-menubar", "gui-sidebar", "gui-symbol", "mode-toggle", "pt-help"]) expect(all).toContain(part);
  });
});
