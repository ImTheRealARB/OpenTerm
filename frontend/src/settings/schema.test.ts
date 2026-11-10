import { describe, expect, it } from "vitest";
import { DEFAULTS, POLL_BOUNDS, cycle, diffFromDefaults, isZone, normalize, reconcile, stepPoll, CHART_RANGES } from "./schema";
import { settingsArgs, themeArgs } from "./commands";

describe("normalize", () => {
  it("returns the defaults for empty or non-object input", () => {
    expect(normalize(undefined).settings).toEqual(DEFAULTS);
    expect(normalize(null).errors).toEqual([]);
    const bad = normalize("nope");
    expect(bad.settings).toEqual(DEFAULTS);
    expect(bad.errors).toContain("settings is not an object");
  });

  it("keeps valid fields and fills the rest", () => {
    const { settings, errors } = normalize({ theme: "green", vim: true, chart: { range: "6M" }, poll: { news: 120 } });
    expect(errors).toEqual([]);
    expect(settings.theme).toBe("green");
    expect(settings.vim).toBe(true);
    expect(settings.chart).toEqual({ range: "6M", type: "CANDLE" });
    expect(settings.poll).toEqual({ ...DEFAULTS.poll, news: 120 });
  });

  it("falls back per field and reports what was dropped", () => {
    const { settings, errors } = normalize({
      theme: "neon", vim: "yes", clocks: ["Mars/Base"], poll: { news: 5, crypto: 30.5, sources: 20 },
      numberFormat: { thousands: ".", decimal: "." }, keys: { goTo: "Ctrl+G" },
    });
    expect(settings.theme).toBe("amber");
    expect(settings.vim).toBe(false);
    expect(settings.clocks).toEqual(["LOCAL", "UTC"]);
    expect(settings.poll.news).toBe(DEFAULTS.poll.news);
    expect(settings.poll.crypto).toBe(DEFAULTS.poll.crypto);
    expect(settings.poll.sources).toBe(20);
    expect(settings.numberFormat).toEqual(DEFAULTS.numberFormat);
    expect(errors).toEqual(expect.arrayContaining(["theme", "vim", "clocks", "poll.news", "poll.crypto", "numberFormat", "keys.goTo"]));
  });

  it("accepts up to three clocks and dedupes key chords", () => {
    expect(normalize({ clocks: ["LOCAL", "UTC", "America/New_York"] }).errors).toEqual([]);
    expect(normalize({ clocks: ["LOCAL", "UTC", "Asia/Kolkata", "Europe/London"] }).settings.clocks).toEqual(["LOCAL", "UTC"]);
    expect(normalize({ keys: { help: ["Ctrl+H", "Ctrl+H"] } }).settings.keys).toEqual({ help: ["Ctrl+H"] });
  });
});

describe("mode (GUI / terminal)", () => {
  it("defaults to gui when nothing was ever saved", () => {
    expect(DEFAULTS.mode).toBe("gui");
    expect(normalize(undefined).settings.mode).toBe("gui");
    expect(normalize(null).settings.mode).toBe("gui");
  });

  it("reads a saved object without a mode as terminal (existing users keep their terminal)", () => {
    expect(normalize({}).settings.mode).toBe("terminal");
    expect(normalize({ theme: "green" }).settings.mode).toBe("terminal");
    expect(normalize({}).errors).toEqual([]);
  });

  it("keeps a valid saved mode", () => {
    expect(normalize({ mode: "gui" }).settings.mode).toBe("gui");
    expect(normalize({ mode: "terminal" }).settings.mode).toBe("terminal");
  });

  it("reports an invalid mode and falls back to terminal", () => {
    for (const bad of ["tui", 1, true, "GUI"]) {
      const r = normalize({ mode: bad });
      expect(r.settings.mode).toBe("terminal");
      expect(r.errors).toContain("mode");
    }
  });

  it("round-trips through diffFromDefaults: gui is stored, terminal is the absent-field default", () => {
    const gui = { ...DEFAULTS, mode: "gui" as const };
    const term = { ...DEFAULTS, mode: "terminal" as const };
    expect(diffFromDefaults(gui)).toEqual({ mode: "gui" });
    expect(diffFromDefaults(term)).toEqual({}); // same stored document as before GUI mode existed
    expect(normalize(diffFromDefaults(gui)).settings.mode).toBe("gui");
    expect(normalize(diffFromDefaults(term)).settings.mode).toBe("terminal");
  });

  it("SETTINGS MODE switches the shell and rejects other words", () => {
    const r = settingsArgs(["MODE", "TERMINAL"], DEFAULTS);
    expect(r && r.ok && r.next.mode).toBe("terminal");
    const g = settingsArgs(["MODE", "gui"], { ...DEFAULTS, mode: "terminal" });
    expect(g && g.ok && g.next.mode).toBe("gui");
    expect(settingsArgs(["MODE", "FANCY"], DEFAULTS)).toMatchObject({ ok: false });
    expect(settingsArgs(["MODE"], DEFAULTS)).toMatchObject({ ok: false });
  });

  it("SETTINGS RESET keeps the current mode", () => {
    const r = settingsArgs(["RESET"], { ...DEFAULTS, mode: "terminal", theme: "green" });
    expect(r && r.ok && r.next.mode).toBe("terminal");
    expect(r && r.ok && r.next.theme).toBe("amber");
  });
});

describe("zones", () => {
  it("knows LOCAL, UTC and IANA zones only", () => {
    expect(isZone("LOCAL")).toBe(true);
    expect(isZone("UTC")).toBe(true);
    expect(isZone("Asia/Kolkata")).toBe(true);
    expect(isZone("local")).toBe(false);
    expect(isZone("Nowhere/City")).toBe(false);
    expect(isZone(5)).toBe(false);
  });
});

describe("diffFromDefaults", () => {
  it("is empty for the defaults and holds only changed fields otherwise", () => {
    // DEFAULTS is gui mode, and "gui" is always written out (see the mode tests above).
    expect(diffFromDefaults(DEFAULTS)).toEqual({ mode: "gui" });
    expect(diffFromDefaults({ ...DEFAULTS, mode: "terminal" })).toEqual({});
    const s = { ...DEFAULTS, mode: "terminal" as const, theme: "light" as const, keys: { help: ["Ctrl+H"] } };
    expect(diffFromDefaults(s)).toEqual({ theme: "light", keys: { help: ["Ctrl+H"] } });
  });
});

describe("cycle and stepPoll", () => {
  it("wraps in both directions", () => {
    expect(cycle(["a", "b", "c"], "c", 1)).toBe("a");
    expect(cycle(["a", "b", "c"], "a", -1)).toBe("c");
    expect(cycle(["a", "b", "c"], "zzz" as never, 1)).toBe("b");
    expect(cycle(CHART_RANGES, "MAX", 1)).toBe("1D");
  });

  it("stays inside the poll bounds", () => {
    const [lo, hi] = POLL_BOUNDS.news;
    expect(stepPoll("news", lo, -1)).toBe(lo);
    expect(stepPoll("news", hi, 1)).toBe(hi);
    expect(stepPoll("news", 60, 1)).toBe(90);
    expect(stepPoll("news", 60, -1)).toBe(55);
  });
});

describe("reconcile", () => {
  it("decides between push, adopt and keep", () => {
    expect(reconcile({ updatedAt: 0, dirty: false }, { settings: null, updated_at: null })).toBe("keep");
    expect(reconcile({ updatedAt: 5, dirty: false }, { settings: null, updated_at: null })).toBe("push");
    expect(reconcile({ updatedAt: 9, dirty: true }, { settings: {}, updated_at: 5 })).toBe("push");
    expect(reconcile({ updatedAt: 3, dirty: true }, { settings: {}, updated_at: 5 })).toBe("adopt");
    expect(reconcile({ updatedAt: 5, dirty: false }, { settings: {}, updated_at: 5 })).toBe("keep");
    expect(reconcile({ updatedAt: 2, dirty: false }, { settings: {}, updated_at: 5 })).toBe("adopt");
  });
});

describe("command arguments", () => {
  it("THEME: bare opens SETTINGS, a name switches, junk fails", () => {
    expect(themeArgs([], DEFAULTS)).toBeNull();
    const r = themeArgs(["GREEN"], DEFAULTS);
    expect(r && r.ok && r.next.theme).toBe("green");
    expect(themeArgs(["pink"], DEFAULTS)).toMatchObject({ ok: false });
  });

  it("SETTINGS VIM / CHART / POLL / numbers", () => {
    const on = settingsArgs(["VIM", "ON"], DEFAULTS);
    expect(on && on.ok && on.next.vim).toBe(true);
    expect(settingsArgs(["VIM"], DEFAULTS)).toMatchObject({ ok: false });
    const ch = settingsArgs(["CHART", "6M", "LINE"], DEFAULTS);
    expect(ch && ch.ok && ch.next.chart).toEqual({ range: "6M", type: "LINE" });
    expect(settingsArgs(["CHART", "XX"], DEFAULTS)).toMatchObject({ ok: false });
    const p = settingsArgs(["POLL", "NEWS", "120"], DEFAULTS);
    expect(p && p.ok && p.next.poll.news).toBe(120);
    expect(settingsArgs(["POLL", "NEWS", "1"], DEFAULTS)).toMatchObject({ ok: false });
  });

  it("SETTINGS DECIMAL COMMA needs a different thousands separator", () => {
    expect(settingsArgs(["DECIMAL", "COMMA"], DEFAULTS)).toMatchObject({ ok: false });
    const cur = { ...DEFAULTS, numberFormat: { thousands: ".", decimal: "," } as const };
    expect(settingsArgs(["THOUSANDS", "SPACE"], cur)).toMatchObject({ ok: true });
  });

  it("SETTINGS CLOCKS canonicalises zones and RESET restores defaults", () => {
    const c = settingsArgs(["CLOCKS", "local", "america/new_york"], DEFAULTS);
    expect(c && c.ok && c.next.clocks).toEqual(["LOCAL", "America/New_York"]);
    expect(settingsArgs(["CLOCKS", "Mars/Base"], DEFAULTS)).toMatchObject({ ok: false });
    const r = settingsArgs(["RESET"], { ...DEFAULTS, theme: "light", vim: true });
    expect(r && r.ok && r.next).toEqual(DEFAULTS);
    expect(settingsArgs([], DEFAULTS)).toBeNull();
  });
});

describe("AI settings", () => {
  it("defaults to the Phase 16 models and keeps valid ai fields, dropping bad ones", () => {
    expect(DEFAULTS.ai).toEqual({ model: "deepseek/deepseek-v4-pro", visionModel: "deepseek/deepseek-v4.1-flash", provider: "openrouter", storeText: false });
    expect(normalize({ ai: { model: "anthropic/claude-sonnet-5.5", provider: "anthropic" } }).settings.ai).toEqual({ ...DEFAULTS.ai, model: "anthropic/claude-sonnet-5.5", provider: "anthropic" });
    const bad = normalize({ ai: { model: "bad model!", provider: "skynet", visionModel: 5 } });
    expect(bad.settings.ai).toEqual(DEFAULTS.ai);
    expect(bad.errors).toEqual(expect.arrayContaining(["ai.model", "ai.provider", "ai.visionModel"]));
  });

  it("stores only a changed ai block", () => {
    expect(diffFromDefaults(DEFAULTS).ai).toBeUndefined();
    expect(diffFromDefaults({ ...DEFAULTS, ai: { ...DEFAULTS.ai, model: "x/y" } }).ai).toEqual({ ...DEFAULTS.ai, model: "x/y" });
  });

  it("keeps ai.storeText through normalize and diffFromDefaults, rejecting a non-boolean", () => {
    expect(normalize({ ai: { storeText: true } }).settings.ai.storeText).toBe(true);
    const bad = normalize({ ai: { storeText: "yes" } });
    expect(bad.settings.ai.storeText).toBe(false);
    expect(bad.errors).toContain("ai.storeText");
    expect(diffFromDefaults({ ...DEFAULTS, ai: { ...DEFAULTS.ai, storeText: true } }).ai).toEqual({ ...DEFAULTS.ai, storeText: true });
  });

  it("SETTINGS AI STORETEXT ON|OFF", () => {
    const on = settingsArgs(["AI", "STORETEXT", "ON"], DEFAULTS);
    expect(on && on.ok && on.next.ai.storeText).toBe(true);
    const off = settingsArgs(["AI", "STORETEXT", "OFF"], { ...DEFAULTS, ai: { ...DEFAULTS.ai, storeText: true } });
    expect(off && off.ok && off.next.ai.storeText).toBe(false);
    expect(settingsArgs(["AI", "STORETEXT", "MAYBE"], DEFAULTS)).toMatchObject({ ok: false });
    expect(settingsArgs(["AI", "STORETEXT"], DEFAULTS)).toMatchObject({ ok: false });
    const reset = settingsArgs(["AI", "RESET"], { ...DEFAULTS, ai: { ...DEFAULTS.ai, storeText: true } });
    expect(reset && reset.ok && reset.next.ai.storeText).toBe(false);
  });

  it("SETTINGS AI MODEL / VISION / PROVIDER / RESET", () => {
    const m = settingsArgs(["AI", "MODEL", "deepseek/deepseek-v4-flash"], DEFAULTS);
    expect(m && m.ok && m.next.ai.model).toBe("deepseek/deepseek-v4-flash");
    const v = settingsArgs(["AI", "VISION", "google/gemma-4-31b-it:free"], DEFAULTS);
    expect(v && v.ok && v.next.ai.visionModel).toBe("google/gemma-4-31b-it:free");
    const p = settingsArgs(["AI", "PROVIDER", "ollama"], DEFAULTS);
    expect(p && p.ok && p.next.ai.provider).toBe("ollama");
    expect(settingsArgs(["AI", "PROVIDER", "skynet"], DEFAULTS)).toMatchObject({ ok: false });
    expect(settingsArgs(["AI", "MODEL", "not a model"], DEFAULTS)).toMatchObject({ ok: false });
    expect(settingsArgs(["AI", "MODEL"], DEFAULTS)).toMatchObject({ ok: false });
    const r = settingsArgs(["AI", "RESET"], { ...DEFAULTS, ai: { ...DEFAULTS.ai, model: "x/y" } });
    expect(r && r.ok && r.next.ai).toEqual(DEFAULTS.ai);
  });
});
