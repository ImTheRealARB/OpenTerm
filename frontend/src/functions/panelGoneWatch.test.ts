import { describe, expect, it, vi } from "vitest";
import { watchPanelGone } from "./panelGoneWatch";
import { workspace, replaceView, closePanel, split } from "../state/workspace";
import { latestOnly } from "../state/latestOnly";

describe("watchPanelGone", () => {
  it("fires at once when the panel is already closed (audit H-30: closed while loadLists() was pending)", () => {
    const onGone = vi.fn();
    watchPanelGone(987654, onGone);
    expect(onGone).toHaveBeenCalledTimes(1);
  });

  it("still fires once on a later view replacement or close", () => {
    const id = workspace.get().focus;
    const onGone = vi.fn();
    const off = watchPanelGone(id, onGone);
    expect(onGone).not.toHaveBeenCalled();
    replaceView(id, (v) => ({ ...v, args: ["X"] }));
    expect(onGone).toHaveBeenCalledTimes(1);
    off();
  });

  it("fires when the panel is closed after the watch started", () => {
    const second = split("v");
    expect(second).not.toBeNull();
    const onGone = vi.fn();
    const off = watchPanelGone(second!, onGone);
    closePanel(second!);
    expect(onGone).toHaveBeenCalledTimes(1);
    off();
  });
});

describe("latestOnly (an older run must not write over a newer one)", () => {
  it("only the newest ticket is current", () => {
    const l = latestOnly();
    const a = l.next();
    expect(l.isCurrent(a)).toBe(true);
    const b = l.next();
    expect(l.isCurrent(a)).toBe(false);
    expect(l.isCurrent(b)).toBe(true);
  });
});
