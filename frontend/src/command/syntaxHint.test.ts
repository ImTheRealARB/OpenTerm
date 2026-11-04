import { describe, expect, it } from "vitest";
import { FUNCTIONS, isFunction } from "../functions/registry";
import { slotValues, splitSchema, syntaxHint } from "./syntaxHint";
import { needsNatural } from "./nlRun";

const env = { isFunction, argsSchema: (c: string) => FUNCTIONS.get(c)?.argsSchema, symbols: ["AAPL", "MSFT", "AMZN"] };
const activeText = (t: string) => syntaxHint(t, env)?.slots.find((s) => s.active)?.text;

describe("schema splitting", () => {
  it("splits bracket groups", () => {
    expect(splitSchema("[A|Q] [IS|BS|CF]")).toEqual(["[A|Q]", "[IS|BS|CF]"]);
    expect(splitSchema("[VS SYM] [LOG]")).toEqual(["[VS SYM]", "[LOG]"]);
    expect(splitSchema("SERIES_ID [1Y|2Y]")).toEqual(["SERIES_ID", "[1Y|2Y]"]);
    expect(splitSchema("")).toEqual([]);
  });
  it("expands ranges and alternatives", () => {
    expect(slotValues("[1D..MAX]")).toContain("5Y");
    expect(slotValues("[1M..MAX]")).not.toContain("1D");
    expect(slotValues("[D|W|MO|5MIN|1H]")).toEqual(["D", "W", "MO", "5MIN", "1H"]);
    expect(slotValues("[VS SYM]")).toEqual(["VS"]);
  });
});

describe("syntax hint", () => {
  it("shows nothing without a function code", () => {
    expect(syntaxHint("", env)).toBeNull();
    expect(syntaxHint("AAPL ", env)).toBeNull();
    expect(syntaxHint("apple chart", env)).toBeNull();
  });
  it("marks the range slot of GP after a space", () => {
    const h = syntaxHint("AAPL GP ", env)!;
    expect(h.code).toBe("GP");
    expect(h.slots[0]).toEqual({ text: "[1D..MAX]", active: true });
    expect(h.values).toContain("1Y");
    expect(h.token).toBe("");
  });
  it("moves on once a slot is used", () => {
    expect(activeText("AAPL GP 5Y ")).toBe("[D|W|MO|5MIN|1H]");
    expect(activeText("AAPL FA ")).toBe("[A|Q]");
    expect(activeText("AAPL FA Q ")).toBe("[IS|BS|CF]");
  });
  it("follows the partial word", () => {
    const h = syntaxHint("AAPL GP 5", env)!;
    expect(h.values).toEqual(["5D", "5Y"]);
    expect(activeText("AAPL FA Q I")).toBe("[IS|BS|CF]");
    expect(syntaxHint("GP RS", env)!.values).toEqual(["RSI"]);
  });
  it("works for a function first, a panel target and no arguments", () => {
    expect(syntaxHint("2: GP ", env)!.code).toBe("GP");
    expect(syntaxHint("FA ", env)!.slots.length).toBe(2);
    expect(syntaxHint("DES ", env)!.slots).toEqual([]);
  });
  it("offers tickers for a SYM slot", () => {
    const h = syntaxHint("Q A", env)!;
    expect(h.wantsSymbol).toBe(true);
    expect(h.values).toEqual(["AAPL", "AMZN"]);
  });
  it("shows the signature while the code itself is still the last word", () => {
    const h = syntaxHint("AAPL GP", env)!;
    expect(h.slots.some((s) => s.active)).toBe(false);
  });
});

describe("when natural language is consulted", () => {
  it("never for exact codes", () => {
    for (const s of ["AAPL", "AAPL GP", "GP", "msft gp", "gp 5y", "2: AAPL GP 5Y", "AAPL N", "WL", "MSFT US GP"]) expect(needsNatural(s)).toBe(false);
  });
  it("for failed grammar and lower-case single words", () => {
    for (const s of ["apple stock price chart", "tesla news", "apple", "Tesla", "bank of america"]) expect(needsNatural(s)).toBe(true);
  });
  it("not for short or symbol-only text", () => {
    for (const s of ["", "a", "^GSPC", "BRK-B", "12"]) expect(needsNatural(s)).toBe(false);
  });
});
