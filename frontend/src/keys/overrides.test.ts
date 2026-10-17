import { describe, expect, it } from "vitest";
import defaults from "./keybindings.json";
import { BROWSER_RESERVED, buildIndex, checkChord, diffBindings, expand, mergeBindings, type Bindings } from "./overrides";

const D = defaults as Bindings;

describe("expand", () => {
  it("expands the 1..9 range and leaves plain chords alone", () => {
    const e = expand("Alt+1..9");
    expect(e).toHaveLength(9);
    expect(e[0]).toEqual({ chord: "Alt+1", n: 1 });
    expect(e[8]).toEqual({ chord: "Alt+9", n: 9 });
    expect(expand("Ctrl+K")).toEqual([{ chord: "Ctrl+K" }]);
  });
});

describe("mergeBindings", () => {
  it("replaces an action's chords and keeps the rest", () => {
    const m = mergeBindings(D, { maximize: ["Ctrl+M"] });
    expect(m.maximize).toEqual(["Ctrl+M"]);
    expect(m.refresh).toEqual(D.refresh);
  });

  it("ignores fixed and unknown actions", () => {
    const m = mergeBindings(D, { escape: ["Ctrl+E"], focusPanel: ["Ctrl+P"], nope: ["Ctrl+N"] });
    expect(m.escape).toEqual(["Escape"]);
    expect(m.focusPanel).toEqual(D.focusPanel);
    expect("nope" in m).toBe(false);
  });

  it("does not mutate the defaults", () => {
    const before = JSON.stringify(D);
    mergeBindings(D, { maximize: ["Ctrl+M"] });
    expect(JSON.stringify(D)).toBe(before);
  });
});

describe("buildIndex", () => {
  it("maps each chord to its action, with the number for ranges", () => {
    const idx = buildIndex(D);
    expect(idx.get("Ctrl+K")).toEqual({ action: "focusCommand", n: undefined });
    expect(idx.get("Alt+3")).toEqual({ action: "focusPanel", n: 3 });
  });

  it("lets the first action win on a duplicate", () => {
    const idx = buildIndex({ a: ["Ctrl+X"], b: ["Ctrl+X"] });
    expect(idx.get("Ctrl+X")?.action).toBe("a");
  });
});

describe("checkChord", () => {
  it("accepts a free modified chord", () => {
    expect(checkChord(D, "maximize", "Ctrl+M")).toEqual({ ok: true });
    expect(checkChord(D, "maximize", "Alt+Shift+M")).toEqual({ ok: true });
  });

  it("refuses unknown and fixed actions", () => {
    expect(checkChord(D, "nope", "Ctrl+M")).toMatchObject({ ok: false });
    expect(checkChord(D, "escape", "Ctrl+M")).toMatchObject({ ok: false, reason: "THIS SHORTCUT IS FIXED" });
  });

  it("refuses browser-reserved chords", () => {
    for (const c of ["Ctrl+W", "Ctrl+T", "Ctrl+3"]) {
      expect(BROWSER_RESERVED.has(c)).toBe(true);
      expect(checkChord(D, "maximize", c)).toMatchObject({ ok: false });
    }
  });

  it("refuses bare letters, plain navigation keys and a lone modifier", () => {
    expect(checkChord(D, "maximize", "M")).toMatchObject({ ok: false });
    expect(checkChord(D, "maximize", "Shift+M")).toMatchObject({ ok: false });
    expect(checkChord(D, "maximize", "ArrowUp")).toMatchObject({ ok: false });
    expect(checkChord(D, "maximize", "Ctrl")).toMatchObject({ ok: false });
    expect(checkChord(D, "maximize", "")).toMatchObject({ ok: false });
  });

  it("reports the action that already owns a chord", () => {
    const owner = Object.entries(D).find(([a, c]) => a !== "maximize" && c.some((x) => x.startsWith("Ctrl+") && !BROWSER_RESERVED.has(x) && !x.includes("..")));
    expect(owner).toBeTruthy();
    const chord = owner![1].find((x) => x.startsWith("Ctrl+") && !BROWSER_RESERVED.has(x) && !x.includes(".."))!;
    expect(checkChord(D, "maximize", chord)).toMatchObject({ ok: false, conflict: owner![0] });
  });

  it("reserves the vim half-page chords only while vim is on", () => {
    expect(checkChord(D, "maximize", "Ctrl+D", { vim: true })).toMatchObject({ ok: false });
    expect(checkChord(D, "maximize", "Ctrl+D", { vim: false }).ok).toBe(true);
  });
});

describe("diffBindings", () => {
  it("returns only the actions that differ from the defaults", () => {
    const eff = mergeBindings(D, { maximize: ["Ctrl+M"], refresh: [...D.refresh] });
    expect(diffBindings(D, eff)).toEqual({ maximize: ["Ctrl+M"] });
  });

  it("is empty for unchanged bindings and round-trips with mergeBindings", () => {
    expect(diffBindings(D, mergeBindings(D, undefined))).toEqual({});
    const o = { maximize: ["Ctrl+M", "Alt+M"] };
    expect(diffBindings(D, mergeBindings(D, o))).toEqual(o);
  });
});
