import { describe, expect, it } from "vitest";
import { symbolCommand } from "./search";

const ITEMS = [
  { code: "GP", title: "Price chart" },
  { code: "N", title: "News" },
];
const isFn = (c: string) => ITEMS.some((i) => i.code === c);

describe("symbolCommand", () => {
  const needs = (c: string) => c === "GP";
  it("keeps a security-based function of the focused panel", () => {
    expect(symbolCommand("aapl", { currentFn: "GP", isFunction: isFn, needsSecurity: needs })).toBe("aapl GP");
  });
  it("uses the plain ticker when the panel function takes no security", () => {
    expect(symbolCommand("AAPL", { currentFn: "N", isFunction: isFn, needsSecurity: needs })).toBe("AAPL");
    expect(symbolCommand("AAPL", { isFunction: isFn, needsSecurity: needs })).toBe("AAPL");
  });
  it("passes spaced text and function codes through untouched", () => {
    expect(symbolCommand("RELIANCE IN GP", { currentFn: "N", isFunction: isFn, needsSecurity: needs })).toBe("RELIANCE IN GP");
    expect(symbolCommand("GP", { currentFn: "GP", isFunction: isFn, needsSecurity: needs })).toBe("GP");
    expect(symbolCommand("", { isFunction: isFn, needsSecurity: needs })).toBeNull();
  });
});
