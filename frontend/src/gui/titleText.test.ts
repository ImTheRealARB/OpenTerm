import { describe, expect, it } from "vitest";
import { shortTitle } from "./titleText";

describe("shortTitle", () => {
  it("keeps a plain title", () => {
    expect(shortTitle("Price chart")).toBe("Price chart");
  });
  it("drops a parenthesis and anything after a colon", () => {
    expect(shortTitle("Quote monitor (live)")).toBe("Quote monitor");
    expect(shortTitle("Energy board: crude, natural gas, refined products")).toBe("Energy board");
  });
  it("shortens a very long clause", () => {
    expect(shortTitle("A".repeat(60)).length).toBeLessThanOrEqual(40);
  });
});
