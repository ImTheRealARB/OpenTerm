import { describe, expect, it } from "vitest";
import { carryNulls } from "./tickMerge";

type R = (number | string | null)[];

describe("review: tick buffer keeps fields from an earlier tick of the same frame", () => {
  it("fills only the null slots from the previous buffered row", () => {
    const prev: R = ["AAPL", 100, 1.5, 1.2, 5000, 101, 99, 1000, "y"];
    const next: R = ["AAPL", 101, null, null, null, 102, null, 1001, "y"];
    carryNulls(prev, next);
    expect(next).toEqual(["AAPL", 101, 1.5, 1.2, 5000, 102, 99, 1001, "y"]);
  });

  it("never touches price, time or src, and ignores a missing previous row", () => {
    const next: R = ["X", 5, null, null, null, null, null, 7, "p"];
    carryNulls(undefined, next);
    expect(next).toEqual(["X", 5, null, null, null, null, null, 7, "p"]);
    carryNulls(["X", 1, 2, 3, 4, 5, 6, 1, "y"], next);
    expect(next.slice(0, 2)).toEqual(["X", 5]);
    expect(next.slice(7)).toEqual([7, "p"]);
  });
});
