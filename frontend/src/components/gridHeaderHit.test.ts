import { describe, expect, it } from "vitest";
import { headerHit } from "./gridHeaderHit";

describe("headerHit", () => {
  const xs = [0, 100, 150, 400];
  it("maps x to the column whose span holds it", () => {
    expect(headerHit(0, xs, 500)).toBe(0);
    expect(headerHit(99, xs, 500)).toBe(0);
    expect(headerHit(100, xs, 500)).toBe(1);
    expect(headerHit(399, xs, 500)).toBe(2);
    expect(headerHit(499, xs, 500)).toBe(3);
  });
  it("is -1 outside the columns or with no columns", () => {
    expect(headerHit(-1, xs, 500)).toBe(-1);
    expect(headerHit(500, xs, 500)).toBe(-1);
    expect(headerHit(5, [], 0)).toBe(-1);
  });
  it("adds the horizontal scroll", () => {
    expect(headerHit(10, xs, 500, 120)).toBe(1);
  });
});
