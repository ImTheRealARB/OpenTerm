import { describe, expect, it } from "vitest";
import { FUNCTIONS } from "../functions/registry";
import { PURPOSE_CODES, purposeOf } from "./purposes";

describe("help drawer purposes", () => {
  it("only name real functions", () => {
    for (const c of PURPOSE_CODES) expect(FUNCTIONS.has(c), c).toBe(true);
  });
  it("are one sentence and fall back to the registry title", () => {
    for (const c of PURPOSE_CODES) {
      const s = purposeOf(c, "x");
      expect(s.endsWith("."), c).toBe(true);
      expect(s.split(". ").length, c).toBeLessThanOrEqual(2);
    }
    expect(purposeOf("ZZZ", "Some function")).toBe("Some function.");
  });
});
