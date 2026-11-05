import { describe, expect, it } from "vitest";
import { firstBlock, moveNav } from "./homeNav";

const counts = [3, 0, 2, 4]; // block 1 has no rows

describe("moveNav", () => {
  it("j / k move inside a block and stop at its ends", () => {
    expect(moveNav(counts, { b: 0, r: 0 }, "j")).toEqual({ b: 0, r: 1 });
    expect(moveNav(counts, { b: 0, r: 2 }, "ArrowDown")).toEqual({ b: 0, r: 2 });
    expect(moveNav(counts, { b: 0, r: 0 }, "k")).toEqual({ b: 0, r: 0 });
  });

  it("l / h hop to the next / previous block with rows, wrapping, and clamp the row", () => {
    expect(moveNav(counts, { b: 0, r: 2 }, "l")).toEqual({ b: 2, r: 1 }); // skips the empty block 1; row 2 becomes the last row of block 2
    expect(moveNav(counts, { b: 3, r: 3 }, "ArrowRight")).toEqual({ b: 0, r: 2 }); // wraps
    expect(moveNav(counts, { b: 0, r: 1 }, "h")).toEqual({ b: 3, r: 1 });
    expect(moveNav(counts, { b: 2, r: 0 }, "ArrowLeft")).toEqual({ b: 0, r: 0 });
  });

  it("g / G go to the first / last row; other keys are not movement", () => {
    expect(moveNav(counts, { b: 3, r: 2 }, "g")).toEqual({ b: 3, r: 0 });
    expect(moveNav(counts, { b: 3, r: 0 }, "G")).toEqual({ b: 3, r: 3 });
    expect(moveNav(counts, { b: 0, r: 0 }, "x")).toBeNull();
    expect(moveNav(counts, { b: 0, r: 0 }, "Enter")).toBeNull();
  });

  it("with no rows anywhere nothing moves", () => {
    expect(moveNav([0, 0], { b: 0, r: 0 }, "l")).toEqual({ b: 0, r: 0 });
    expect(firstBlock([0, 0, 5])).toBe(2);
    expect(firstBlock([0, 0])).toBe(0);
  });
});
