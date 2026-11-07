import { describe, expect, it } from "vitest";
import { isPanelKey } from "./panelKeys";

// A minimal stand-in for a KeyboardEvent: vitest runs in Node, which has no KeyboardEvent class.
const ev = (key: string, mods: Partial<{ ctrlKey: boolean; altKey: boolean; metaKey: boolean }> = {}) => ({
  key, ctrlKey: false, altKey: false, metaKey: false, ...mods,
});

describe("isPanelKey: the one chord guard for panel key handlers", () => {
  it("lets plain keys through, including Shift+letter and symbols", () => {
    expect(isPanelKey(ev("j"))).toBe(true);
    expect(isPanelKey(ev("R"))).toBe(true); // Shift+R arrives as an upper-case key
    expect(isPanelKey(ev("?"))).toBe(true);
    expect(isPanelKey(ev("Enter"))).toBe(true);
    expect(isPanelKey(ev("Escape"))).toBe(true);
  });
  it("drops Ctrl, Alt and Meta chords so Ctrl+K reaches the command line", () => {
    expect(isPanelKey(ev("k", { ctrlKey: true }))).toBe(false);
    expect(isPanelKey(ev("1", { altKey: true }))).toBe(false);
    expect(isPanelKey(ev("x", { metaKey: true }))).toBe(false);
  });
  it("drops a bare modifier keydown (the event sent before Shift+R or Ctrl+K)", () => {
    for (const k of ["Shift", "Control", "Alt", "Meta"]) expect(isPanelKey(ev(k))).toBe(false);
  });
});
