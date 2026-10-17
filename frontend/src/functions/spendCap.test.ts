import { describe, expect, it } from "vitest";
import { parseCap, spendLine } from "./spendCap";

describe("APIKEYS spend cap", () => {
  it("parses dollar amounts to cents", () => {
    expect(parseCap("2")).toBe(2);
    expect(parseCap(" $2.505 ")).toBe(2.51);
    expect(parseCap("US$ 0.5")).toBe(0.5);
    expect(parseCap(".25")).toBe(0.25);
    expect(parseCap("0")).toBe(0);
  });
  it("rejects junk and out-of-range caps", () => {
    for (const t of ["", "abc", "-1", "1e3", "1001", "2,5"]) expect(parseCap(t)).toBeNull();
  });
  it("formats the line", () => {
    expect(spendLine({ today: 0.123, cap: 1 })).toBe("AI SPEND TODAY US$0.12 / 1.00 CAP");
    expect(spendLine(undefined)).toBe("AI SPEND TODAY —");
  });
});
