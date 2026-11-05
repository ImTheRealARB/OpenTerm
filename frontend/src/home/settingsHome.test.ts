// Settings added for HOME: startup, tape, tapeSymbols (schema + command parser).
import { describe, expect, it } from "vitest";
import { settingsArgs } from "../settings/commands";
import { DEFAULTS, TAPE_DEFAULT, TAPE_MAX, diffFromDefaults, normalize } from "../settings/schema";

describe("startup / tape settings", () => {
  it("default: HOME on start-up, no top-bar tape, the default symbols", () => {
    expect(DEFAULTS.startup).toBe("home");
    expect(DEFAULTS.tape).toBe(false);
    expect(DEFAULTS.tapeSymbols).toEqual([...TAPE_DEFAULT]);
    expect(normalize(undefined).settings.startup).toBe("home");
    // a user who saved settings before HOME existed also gets the default
    expect(normalize({ theme: "green" }).settings.startup).toBe("home");
  });

  it("accepts valid values and keeps them out of the stored diff only when they equal the defaults", () => {
    const { settings, errors } = normalize({ startup: "layout", tape: true, tapeSymbols: ["AAPL", "^GSPC", "BTC-USD"] });
    expect(errors).toEqual([]);
    expect(settings.startup).toBe("layout");
    expect(settings.tape).toBe(true);
    expect(settings.tapeSymbols).toEqual(["AAPL", "^GSPC", "BTC-USD"]);
    expect(diffFromDefaults(settings)).toMatchObject({ startup: "layout", tape: true, tapeSymbols: ["AAPL", "^GSPC", "BTC-USD"] });
    expect(diffFromDefaults(DEFAULTS)).not.toHaveProperty("startup");
  });

  it("an empty tape is allowed", () => {
    expect(normalize({ tapeSymbols: [] }).settings.tapeSymbols).toEqual([]);
  });

  it("drops bad values field by field and says which", () => {
    const tooMany = Array.from({ length: TAPE_MAX + 1 }, (_, i) => `S${i}`);
    for (const bad of [{ startup: "welcome" }, { tape: "yes" }, { tapeSymbols: tooMany }, { tapeSymbols: ["aapl"] }, { tapeSymbols: ["A B"] }, { tapeSymbols: ["AAPL", "AAPL"] }, { tapeSymbols: "AAPL" }]) {
      const { settings, errors } = normalize(bad);
      expect(errors.length).toBe(1);
      expect(settings.startup).toBe(DEFAULTS.startup);
      expect(settings.tapeSymbols).toEqual(DEFAULTS.tapeSymbols);
      expect(settings.tape).toBe(DEFAULTS.tape);
    }
  });

  it("SETTINGS STARTUP and SETTINGS TAPE", () => {
    expect(settingsArgs(["STARTUP", "layout"], DEFAULTS)).toMatchObject({ ok: true, next: { startup: "layout" } });
    expect(settingsArgs(["STARTUP", "HOME"], { ...DEFAULTS, startup: "layout" })).toMatchObject({ ok: true, next: { startup: "home" } });
    expect(settingsArgs(["STARTUP", "x"], DEFAULTS)).toMatchObject({ ok: false });
    expect(settingsArgs(["TAPE", "on"], DEFAULTS)).toMatchObject({ ok: true, next: { tape: true } });
    expect(settingsArgs(["TAPE"], DEFAULTS)).toMatchObject({ ok: false });
  });
});
