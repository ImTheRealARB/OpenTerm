import { describe, expect, it } from "vitest";
import { settingsArgs } from "./commands";
import { DEFAULTS } from "./schema";

describe("review: SETTINGS POLL with an inherited object key", () => {
  it("SETTINGS POLL CONSTRUCTOR 30 fails with a message instead of throwing", () => {
    const r = settingsArgs(["POLL", "CONSTRUCTOR", "30"], DEFAULTS);
    expect(r).toMatchObject({ ok: false });
  });
  it("SETTINGS POLL __PROTO__ 30 fails with a message instead of throwing", () => {
    const r = settingsArgs(["POLL", "__PROTO__", "30"], DEFAULTS);
    expect(r).toMatchObject({ ok: false });
  });
  it("a real key still works", () => {
    const r = settingsArgs(["POLL", "NEWS", "90"], DEFAULTS);
    expect(r).toMatchObject({ ok: true });
  });
});
