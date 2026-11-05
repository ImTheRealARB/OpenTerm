import { describe, expect, it } from "vitest";
import { settingsArgs } from "./commands";
import { applyFont, fontStack, isFontName } from "./font";
import { DEFAULTS, diffFromDefaults, normalize } from "./schema";

describe("font names", () => {
  it("accepts ordinary installed-font names and the empty default", () => {
    for (const n of ["", "Fira Code", "Cascadia Mono", "Comic Sans MS", "MesloLGS NF", "Source Code Pro", "IBM Plex Mono", "Noto Sans JP", "游ゴシック"]) {
      expect(isFontName(n), n).toBe(true);
    }
  });
  it("rejects anything that could break out of a quoted CSS value", () => {
    for (const n of ['a"b', "a;b", "a{b}", "a\nb", "a,b", "url(x)", "x".repeat(61), " lead", 5, null]) {
      expect(isFontName(n), String(n)).toBe(false);
    }
  });
  it("keeps the built-in stack behind the chosen name", () => {
    expect(fontStack("Fira Code")).toBe('"Fira Code", var(--font-base)');
  });
  it("sets and clears the CSS variable", () => {
    const calls: string[] = [];
    const root = { style: { setProperty: (k: string, v: string) => calls.push(`set ${k} ${v}`), removeProperty: (k: string) => calls.push(`rm ${k}`) } };
    applyFont("Fira Code", root);
    applyFont("", root);
    expect(calls).toEqual(['set --font-user "Fira Code", var(--font-base)', "rm --font-user"]);
  });
});

describe("font setting", () => {
  it("defaults to the built-in font and is left out of storage until changed", () => {
    expect(DEFAULTS.font).toBe("");
    expect(diffFromDefaults(DEFAULTS).font).toBeUndefined();
    expect(diffFromDefaults({ ...DEFAULTS, font: "Fira Code" }).font).toBe("Fira Code");
  });
  it("drops a bad stored value with a note instead of blocking start-up", () => {
    const n = normalize({ font: 'x";y' });
    expect(n.settings.font).toBe("");
    expect(n.errors).toContain("font");
    expect(normalize({ font: "Fira Code" }).settings.font).toBe("Fira Code");
  });
});

describe("SETTINGS FONT", () => {
  it("asks the caller to confirm the font is installed before applying", () => {
    const r = settingsArgs(["FONT", "Fira", "Code"], DEFAULTS);
    expect(r).toMatchObject({ ok: true, checkFont: "Fira Code", next: { font: "Fira Code" } });
  });
  it("DEFAULT resets with no install check", () => {
    const r = settingsArgs(["FONT", "default"], { ...DEFAULTS, font: "Fira Code" });
    expect(r).toMatchObject({ ok: true, next: { font: "" } });
    expect(r && r.ok && r.checkFont).toBeUndefined();
  });
  it("fails loudly on a missing or unsafe name", () => {
    expect(settingsArgs(["FONT"], DEFAULTS)).toMatchObject({ ok: false });
    expect(settingsArgs(["FONT", 'a"b'], DEFAULTS)).toMatchObject({ ok: false });
  });
});
