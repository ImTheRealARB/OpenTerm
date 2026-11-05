import { describe, expect, it } from "vitest";
import { settingsArgs } from "./commands";
import { applyFont, fontStack, isFontName } from "./font";
import { FONT_PRESETS, cyclePreset, findPreset, fontLabel } from "./fontPresets";
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
  it("keeps the built-in stack behind a custom name", () => {
    expect(fontStack("Source Code Pro")).toBe('"Source Code Pro", var(--font-base)');
  });
  it("sets and clears the CSS variable", () => {
    const calls: string[] = [];
    const root = { style: { setProperty: (k: string, v: string) => calls.push(`set ${k} ${v}`), removeProperty: (k: string) => calls.push(`rm ${k}`) } };
    applyFont("Fira Code", root);
    applyFont("Source Code Pro", root);
    applyFont("", root);
    applyFont("JetBrains Mono", root); // the default preset under its own name
    applyFont("GitHub Mono", root);
    expect(calls).toEqual([
      'set --font-user "Fira Code", var(--font-base)',
      'set --font-user "Source Code Pro", var(--font-base)',
      "rm --font-user",
      "rm --font-user",
      `set --font-user ${findPreset("GitHub Mono")!.stack}`,
    ]);
  });
});

describe("presets", () => {
  it("has the requested list in order, default first", () => {
    expect(FONT_PRESETS.map((p) => p.name)).toEqual([
      "", "GitHub Mono", "Geist Mono", "Fira Code", "Mononoki", "Hack", "Monaco", "DejaVu Sans Mono", "Menlo", "Consolas", "Bergoom", "Comic Sans MS",
    ]);
  });
  it("every preset name is a valid stored font name", () => {
    for (const p of FONT_PRESETS) expect(isFontName(p.name), p.label).toBe(true);
  });
  it("finds a preset however it is typed", () => {
    for (const [typed, name] of [["geist mono", "Geist Mono"], ["GEIST-MONO", "Geist Mono"], ["firacode", "Fira Code"], ["github", "GitHub Mono"], ["comic sans", "Comic Sans MS"], ["dejavu", "DejaVu Sans Mono"], ["JetBrains Mono", ""], ["default", ""], ["bloomberg", "Bergoom"]] as const) {
      expect(findPreset(typed)?.name, typed).toBe(name);
    }
    expect(findPreset("Source Code Pro")).toBeUndefined();
  });
  it("cycles with wrap-around and starts custom fonts from the default", () => {
    expect(cyclePreset("", 1).name).toBe("GitHub Mono");
    expect(cyclePreset("", -1).name).toBe("Comic Sans MS");
    expect(cyclePreset("Comic Sans MS", 1).name).toBe("");
    expect(cyclePreset("Source Code Pro", 1).name).toBe("GitHub Mono");
  });
  it("labels a custom font with its own name", () => {
    expect(fontLabel("Source Code Pro")).toBe("Source Code Pro");
    expect(fontLabel("")).toContain("JetBrains Mono");
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
  it("a bundled preset applies with no install check", () => {
    const r = settingsArgs(["FONT", "Fira", "Code"], DEFAULTS);
    expect(r).toMatchObject({ ok: true, next: { font: "Fira Code" } });
    expect(r && r.ok && r.checkFont).toBeUndefined();
  });
  it("a system preset asks for an install check", () => {
    expect(settingsArgs(["FONT", "menlo"], DEFAULTS)).toMatchObject({ ok: true, next: { font: "Menlo" }, checkFont: "Menlo" });
  });
  it("any other name is treated as an installed font and checked", () => {
    expect(settingsArgs(["FONT", "Source", "Code", "Pro"], DEFAULTS)).toMatchObject({ ok: true, next: { font: "Source Code Pro" }, checkFont: "Source Code Pro" });
  });
  it("NEXT and PREV step through the presets; DEFAULT resets", () => {
    expect(settingsArgs(["FONT", "next"], DEFAULTS)).toMatchObject({ ok: true, next: { font: "GitHub Mono" } });
    expect(settingsArgs(["FONT", "prev"], DEFAULTS)).toMatchObject({ ok: true, next: { font: "Comic Sans MS" } });
    expect(settingsArgs(["FONT", "default"], { ...DEFAULTS, font: "Hack" })).toMatchObject({ ok: true, next: { font: "" } });
  });
  it("fails loudly on a missing or unsafe name and lists the presets", () => {
    const none = settingsArgs(["FONT"], DEFAULTS);
    expect(none).toMatchObject({ ok: false });
    expect(none && !none.ok && none.error).toContain("GEIST MONO");
    expect(settingsArgs(["FONT", 'a"b'], DEFAULTS)).toMatchObject({ ok: false });
  });
});
