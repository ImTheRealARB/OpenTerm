import { describe, expect, it } from "vitest";
import {
  cellParts, clampBack, columnsFit, halfFits, ladderRows, levelOf, levelTop, lineY, stepDecimals, visibleBars, zeroY,
} from "./footMath";

describe("which bars are on screen", () => {
  it("shows the newest `cols` bars at back = 0 and slides left as back grows", () => {
    expect(visibleBars(30, 10, 0)).toEqual([20, 30]);
    expect(visibleBars(30, 10, 5)).toEqual([15, 25]);
  });
  it("never scrolls past the oldest page or shows fewer than exist", () => {
    expect(clampBack(99, 30, 10)).toBe(20);
    expect(clampBack(-3, 30, 10)).toBe(0);
    expect(visibleBars(4, 10, 3)).toEqual([0, 4]);
  });
  it("columns and rows fit what the pixels allow", () => {
    expect(columnsFit(1000, 100, 100)).toBe(9);
    expect(columnsFit(50, 100, 100)).toBe(1);
    expect(ladderRows(400, 20)).toBe(20 - 1 - 5);
    expect(ladderRows(40, 20)).toBe(3);
  });
});

describe("which price levels are on screen", () => {
  it("centres on the last price and clamps at both ends", () => {
    expect(levelTop(100, 20, 50, 0)).toBe(60); // top = centre + half the rows
    expect(levelTop(100, 20, 50, 5)).toBe(65); // scrolled up
    expect(levelTop(100, 20, 98, 0)).toBe(99); // cannot go past the highest level
    expect(levelTop(100, 20, 1, 0)).toBe(19); // cannot go below the lowest: the top must leave room for `rows` levels
  });
  it("a short ladder shows every level", () => {
    expect(levelTop(5, 20, 2, 0)).toBe(4);
  });
  it("levelOf maps a price to its row", () => {
    const levels = [100, 101, 102, 103];
    expect(levelOf(101.6, levels, 1)).toBe(1);
    expect(levelOf(50, levels, 1)).toBe(0);
    expect(levelOf(500, levels, 1)).toBe(3);
  });
  it("stepDecimals prints a step without noise", () => {
    expect(stepDecimals(5)).toBe(0);
    expect(stepDecimals(0.5)).toBe(1);
    expect(stepDecimals(0.01)).toBe(2);
    expect(stepDecimals(0.0005)).toBe(4);
  });
});

describe("cell text", () => {
  it("empty sides print nothing", () => {
    expect(cellParts(0, 2)).toEqual({ bid: "", ask: "2.000" });
    expect(cellParts(1.5, 0)).toEqual({ bid: "1.500", ask: "" });
  });
  it("halves fit when each is under half the column minus the x", () => {
    expect(halfFits(5, 13)).toBe(true);
    expect(halfFits(6, 13)).toBe(false);
  });
});

describe("cumulative delta line", () => {
  it("max at the top, min at the bottom, zero included", () => {
    expect(lineY([2, 4], 0, 10)).toEqual([5, 0]); // lo = 0 (zero is always in range), hi = 4
    expect(lineY([-5, 5], 100, 10)).toEqual([110, 100]);
  });
  it("a flat line sits in the middle and the zero line follows the same scale", () => {
    expect(lineY([0, 0], 0, 10)).toEqual([5, 5]);
    expect(zeroY([-5, 5], 100, 10)).toBe(105);
    expect(lineY([], 0, 10)).toEqual([]);
  });
});
