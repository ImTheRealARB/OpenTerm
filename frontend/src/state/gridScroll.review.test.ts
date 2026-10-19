import { describe, expect, it } from "vitest";
import { wheelTop } from "./gridScroll";

describe("review: Grid wheel", () => {
  it("clamps and reports no change at either end (so the canvas is not repainted)", () => {
    expect(wheelTop(0, -100, 50, 10)).toBe(0);
    expect(wheelTop(40, 100, 50, 10)).toBe(40);
    expect(wheelTop(5, 100, 50, 10)).toBe(8);
    expect(wheelTop(5, 0, 50, 10)).toBe(5); // horizontal wheel
    expect(wheelTop(0, 100, 5, 10)).toBe(0); // fewer rows than the viewport
  });
});
