import { describe, expect, it } from "vitest";
import { panelGone } from "./panelGone";

// A tiny workspace with panel 1 showing SWARM and panel 2 showing GP.
const ws = (over: Record<string, unknown> = {}) =>
  ({
    panels: {
      1: { id: 1, views: [{ fn: "SWARM", args: [] }], pos: 0 },
      2: { id: 2, views: [{ fn: "GP", args: [] }], pos: 0 },
    },
    maximized: null,
    ...over,
  }) as never;

describe("panelGone", () => {
  it("is false while the panel still shows the same function", () => {
    expect(panelGone(ws(), 1, "SWARM")).toBe(false);
  });
  it("is false when the panel is maximized (the remount must not abort)", () => {
    expect(panelGone(ws({ maximized: 1 }), 1, "SWARM")).toBe(false);
  });
  it("is true once the panel is removed from the layout", () => {
    const s = ws();
    delete (s as { panels: Record<number, unknown> }).panels[1];
    expect(panelGone(s, 1, "SWARM")).toBe(true);
  });
  it("is true when the panel now runs another function", () => {
    const s = ws();
    (s as { panels: Record<number, { views: { fn: string }[] }> }).panels[1].views[0].fn = "GP";
    expect(panelGone(s, 1, "SWARM")).toBe(true);
  });
});
