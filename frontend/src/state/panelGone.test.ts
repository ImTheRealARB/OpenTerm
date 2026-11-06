import { describe, expect, it } from "vitest";
import { panelGone } from "./panelGone";
import { workspace } from "./workspace";
import type { PanelState, View } from "./workspace";

// Panel 1 shows SWARM and panel 2 shows GP. `swarm` is the view OBJECT a stream would have captured.
const swarm: View = { fn: "SWARM", args: [] };
const ws = (over: Record<string, unknown> = {}) =>
  ({
    panels: {
      1: { id: 1, views: [swarm], pos: 0 },
      2: { id: 2, views: [{ fn: "GP", args: [] }], pos: 0 },
    } as Record<number, PanelState>,
    maximized: null,
    ...over,
  }) as never;

describe("panelGone (compares the view object, not the function code)", () => {
  it("is false while the panel still shows the same view object", () => {
    expect(panelGone(ws(), 1, swarm)).toBe(false);
  });
  it("is false when the panel is maximized (the remount must not abort)", () => {
    expect(panelGone(ws({ maximized: 1 }), 1, swarm)).toBe(false);
  });
  it("is true once the panel is removed from the layout", () => {
    const s = ws() as { panels: Record<number, unknown> };
    delete s.panels[1];
    expect(panelGone(s as never, 1, swarm)).toBe(true);
  });
  it("is true when a second command of the SAME function is typed (new history entry)", () => {
    const s = ws() as { panels: Record<number, PanelState> };
    const second: View = { fn: "SWARM", args: ["OTHER"] };
    s.panels[1] = { id: 1, views: [swarm, second], pos: 1 };
    expect(panelGone(s as never, 1, swarm)).toBe(true);
  });
  it("is true when history steps back to a different entry of the same function", () => {
    const s = ws() as { panels: Record<number, PanelState> };
    s.panels[1] = { id: 1, views: [{ fn: "SWARM", args: ["A"] }, swarm], pos: 0 };
    expect(panelGone(s as never, 1, swarm)).toBe(true);
  });
  it("is true when the panel now runs another function", () => {
    const s = ws() as { panels: Record<number, PanelState> };
    s.panels[1] = { id: 1, views: [{ fn: "GP", args: [] }], pos: 0 };
    expect(panelGone(s as never, 1, swarm)).toBe(true);
  });
  it("is true when the view was rewritten in place (replaceView makes a new object)", () => {
    const s = ws() as { panels: Record<number, PanelState> };
    s.panels[1] = { id: 1, views: [{ ...swarm, args: [] }], pos: 0 };
    expect(panelGone(s as never, 1, swarm)).toBe(true);
  });
});

describe("with the real workspace store", () => {
  it("keeps the view object across maximize, which is why maximize does not abort", async () => {
    const { toggleMaximize } = await import("./workspace");
    const before = workspace.get().panels[workspace.get().focus];
    const view = before.views[before.pos];
    toggleMaximize();
    const after = workspace.get().panels[workspace.get().focus];
    expect(after.views[after.pos]).toBe(view);
    expect(panelGone(workspace.get(), after.id, view)).toBe(false);
    toggleMaximize(); // restore
  });
  it("replaces the view object on navigate and on replaceView", async () => {
    const { navigate, replaceView } = await import("./workspace");
    const id = workspace.get().focus;
    const p0 = workspace.get().panels[id];
    const v0 = p0.views[p0.pos];
    replaceView(id, (v) => ({ ...v, args: ["X"] }));
    expect(panelGone(workspace.get(), id, v0)).toBe(true);
    const p1 = workspace.get().panels[id];
    const v1 = p1.views[p1.pos];
    navigate(id, { fn: "AI", args: [] });
    expect(panelGone(workspace.get(), id, v1)).toBe(true);
  });
});
