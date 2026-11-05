import { describe, expect, it } from "vitest";
import { chgColor, fmtPct, fmtShips, spark } from "./shipFormat";

describe("SHIP formatting", () => {
  it("draws the tallest block for the busiest day and the shortest for the quietest", () => {
    const s = spark([["a", 10], ["b", 20], ["c", 30]]);
    expect(s).toHaveLength(3);
    expect(s[0]).toBe("▁");
    expect(s[2]).toBe("█");
  });
  it("shows a dot for a missing day and nothing for no data", () => {
    expect(spark([["a", 5], ["b", null], ["c", 9]])[1]).toBe("·");
    expect(spark([["a", null]])).toBe("");
  });
  it("keeps only the last `width` days", () => {
    expect(spark(Array.from({ length: 40 }, (_, i) => [String(i), i] as [string, number]), 28)).toHaveLength(28);
  });
  it("formats numbers and leaves unknowns blank", () => {
    expect(fmtShips(41.333)).toBe("41.3");
    expect(fmtShips(null)).toBe("");
    expect(fmtPct(12.44)).toBe("+12.4%");
    expect(fmtPct(-3)).toBe("-3.0%");
    expect(fmtPct(null)).toBe("");
  });
  it("flags big moves only", () => {
    expect(chgColor(-20)).toBe("down");
    expect(chgColor(15)).toBe("up");
    expect(chgColor(5)).toBe("fg");
    expect(chgColor(null)).toBe("dim");
  });
});
