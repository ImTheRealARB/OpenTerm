import { describe, expect, it } from "vitest";
import { applySectorWord } from "./sectorKeys";

const isMarket = (t: string) => ["US", "IN", "LN"].includes(t);
const isFn = (t: string) => ["GP", "DES", "FX"].includes(t);
const ap = (line: string, sticky?: string, s: "EQUITY" | "INDEX" | "CURNCY" = "INDEX") =>
  applySectorWord(line, s, sticky, isMarket, isFn);

describe("applySectorWord", () => {
  it("appends after the security", () => {
    expect(ap("SPX")).toEqual({ ok: true, text: "SPX INDEX " });
  });
  it("goes after the market token", () => {
    expect(ap("AAPL US", undefined, "EQUITY")).toEqual({ ok: true, text: "AAPL US EQUITY " });
  });
  it("replaces an existing sector word", () => {
    expect(ap("SPX INDEX", undefined, "CURNCY")).toEqual({ ok: true, text: "SPX CURNCY " });
    expect(ap("SPX idx GP")).toEqual({ ok: true, text: "SPX INDEX GP " });
  });
  it("goes before the function", () => {
    expect(ap("AAPL GP", undefined, "EQUITY")).toEqual({ ok: true, text: "AAPL EQUITY GP " });
  });
  it("keeps a panel target", () => {
    expect(ap("2: SPX")).toEqual({ ok: true, text: "2: SPX INDEX " });
  });
  it("empty line uses the sticky security or says what to do", () => {
    expect(ap("", "^GSPC")).toEqual({ ok: true, text: "^GSPC INDEX " });
    expect(ap("")).toMatchObject({ ok: false });
  });
  it("refuses a line that starts with a function", () => {
    expect(ap("GP")).toMatchObject({ ok: false });
  });
});
