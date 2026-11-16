import { describe, expect, it } from "vitest";
import { buildNumbering, gutterChars, rowNumbersEffective } from "./rowJump";

describe("rowNumbersEffective", () => {
  it("auto follows the mode: on in Terminal, off in GUI", () => {
    expect(rowNumbersEffective("auto", "terminal")).toBe(true);
    expect(rowNumbersEffective("auto", "gui")).toBe(false);
  });
  it("on and off override the mode", () => {
    expect(rowNumbersEffective("on", "gui")).toBe(true);
    expect(rowNumbersEffective("off", "terminal")).toBe(false);
  });
});

describe("numbering with section headers", () => {
  // header, 3 data rows, header, 2 data rows
  const headers = new Set([0, 4]);
  const nums = buildNumbering(7, (i) => headers.has(i));
  it("counts data rows only; headers get 0 (the 4th data row is row 5: the header at 4 used no number)", () => {
    expect(Array.from(nums)).toEqual([0, 1, 2, 3, 0, 4, 5]);
  });
  it("numbers a grid without headers 1..n", () => {
    expect(Array.from(buildNumbering(3, () => false))).toEqual([1, 2, 3]);
  });
});

describe("gutterChars", () => {
  it("is the widest number plus the closing parenthesis", () => {
    expect(gutterChars(buildNumbering(9, () => false))).toBe(2); // "9)"
    expect(gutterChars(buildNumbering(10, () => false))).toBe(3); // "10)"
    expect(gutterChars(buildNumbering(120, () => false))).toBe(4);
  });
  it("is 0 when there are no data rows", () => {
    expect(gutterChars(buildNumbering(0, () => false))).toBe(0);
    expect(gutterChars(buildNumbering(2, () => true))).toBe(0);
  });
});
