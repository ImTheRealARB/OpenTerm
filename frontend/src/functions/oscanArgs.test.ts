import { describe, expect, it } from "vitest";
import { parseOscanArgs } from "./oscanArgs";

describe("parseOscanArgs", () => {
  it("splits the universe from the filter terms", () => {
    expect(parseOscanArgs(["wl:tech", "ivr>50", "em>5"])).toEqual({ ok: true, universe: "WL:TECH", filter: "IVR>50 EM>5" });
  });
  it("needs a universe", () => {
    expect(parseOscanArgs([]).ok).toBe(false);
  });
});
