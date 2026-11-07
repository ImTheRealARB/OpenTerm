import { beforeEach, describe, expect, it, vi } from "vitest";
import { memClear, memGet, memResetAll, memSet, memSubscribe, pruneMemory } from "./panelMemory";
import type { PanelState } from "./workspace";

const panels = (spec: Record<number, string[]>): { panels: Record<number, PanelState> } => ({
  panels: Object.fromEntries(Object.entries(spec).map(([id, fns]) => [id, { id: Number(id), views: fns.map((fn) => ({ fn, args: [] })), pos: fns.length - 1 }])),
});

describe("panel memory", () => {
  beforeEach(() => memClear());

  it("returns the same reference on every read and keeps the first initial value", () => {
    const init: string[] = [];
    expect(memGet("AI", 1, "turns", init)).toBe(init);
    expect(memGet("AI", 1, "turns", [])).toBe(init); // a different initial is ignored once stored
  });

  it("keeps a value for a later reader (what a remounted panel sees)", () => {
    memGet("AI", 1, "doc", null);
    memSet("AI", 1, "doc", { id: "d1" });
    expect(memGet("AI", 1, "doc", null)).toEqual({ id: "d1" });
  });

  it("separates panels, functions and slots", () => {
    memGet("AI", 1, "turns", 0);
    memGet("AI", 2, "turns", 0);
    memGet("SWARM", 1, "turns", 0);
    memGet("AI", 1, "doc", 0);
    memSet("AI", 1, "turns", 5);
    expect(memGet("AI", 2, "turns", 0)).toBe(0);
    expect(memGet("SWARM", 1, "turns", 0)).toBe(0);
    expect(memGet("AI", 1, "doc", 0)).toBe(0);
  });

  it("supports an updater function and notifies listeners only on a real change", () => {
    memGet("AI", 1, "n", 1);
    const l = vi.fn();
    memSubscribe("AI", 1, "n", 1, l);
    memSet("AI", 1, "n", (p: number) => p + 1);
    expect(memGet("AI", 1, "n", 1)).toBe(2);
    expect(l).toHaveBeenCalledTimes(1);
    memSet("AI", 1, "n", 2); // same value
    expect(l).toHaveBeenCalledTimes(1);
  });

  it("a stream started by an old instance updates whoever is subscribed now", () => {
    memGet("AI", 1, "turns", [] as string[]);
    const oldWrite = (v: string) => memSet("AI", 1, "turns", (p: string[]) => [...p, v]);
    const newReader = vi.fn();
    memSubscribe("AI", 1, "turns", [] as string[], newReader); // the remounted instance
    oldWrite("token");
    expect(newReader).toHaveBeenCalled();
    expect(memGet("AI", 1, "turns", [] as string[])).toEqual(["token"]);
  });

  it("unsubscribe stops notifications", () => {
    memGet("AI", 1, "n", 0);
    const l = vi.fn();
    const off = memSubscribe("AI", 1, "n", 0, l);
    off();
    memSet("AI", 1, "n", 1);
    expect(l).not.toHaveBeenCalled();
  });

  it("is cleared when the panel closes, and a late write does not bring it back", () => {
    memGet("AI", 3, "turns", ["old chat"]);
    pruneMemory(panels({ 1: ["GP"] })); // panel 3 is gone
    memSet("AI", 3, "turns", ["late write from a finished stream"]);
    // A new panel that reuses id 3 starts empty.
    expect(memGet("AI", 3, "turns", [] as string[])).toEqual([]);
  });

  it("is cleared when the panel no longer has that function in its history", () => {
    memGet("AI", 1, "turns", ["chat"]);
    pruneMemory(panels({ 1: ["GP"] })); // e.g. a layout load put a GP panel under id 1
    expect(memGet("AI", 1, "turns", [] as string[])).toEqual([]);
  });

  it("is kept while the function is anywhere in the panel's history (Alt+Left comes back to the chat)", () => {
    memGet("AI", 1, "turns", ["chat"]);
    pruneMemory(panels({ 1: ["AI", "GP"] }));
    expect(memGet("AI", 1, "turns", [] as string[])).toEqual(["chat"]);
  });

  it("memResetAll (layout load) wipes a chat even when the same id still has that function", () => {
    memGet("AI", 1, "turns", [] as string[]);
    memSet("AI", 1, "turns", ["old chat"]);
    const l = vi.fn();
    memSubscribe("AI", 1, "turns", [] as string[], l);
    memResetAll();
    // pruneMemory would keep this (panel 1 still has AI); the reset must not.
    pruneMemory(panels({ 1: ["AI"] }));
    expect(memGet("AI", 1, "turns", ["x"])).toEqual([]);
    expect(l).toHaveBeenCalledTimes(1); // a mounted panel is told, and stays subscribed
    memSet("AI", 1, "turns", ["new chat"]);
    expect(l).toHaveBeenCalledTimes(2);
  });
});
