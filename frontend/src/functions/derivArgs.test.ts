import { describe, expect, it } from "vitest";
import { ctArgs, fxfaArgs, kvParams, omonArgs, wordThenKv } from "./derivArgs";

describe("omonArgs", () => {
  it("recognises a date, a moneyness word and Q= by shape", () => {
    expect(omonArgs(["2026-12-18", "otm", "q=0.5"])).toEqual({ params: { date: "2026-12-18", moneyness: "OTM", q: "0.5" }, bad: [] });
    expect(omonArgs([])).toEqual({ params: {}, bad: [] });
  });
  it("reports anything else instead of guessing", () => {
    expect(omonArgs(["DEC", "ITM"]).bad).toEqual(["DEC"]);
    expect(omonArgs(["Q="]).bad).toEqual(["Q="]);
  });
});

describe("kvParams", () => {
  it("lower-cases keys, keeps values, reports malformed tokens", () => {
    expect(kvParams(["K=350", "TYPE=C", "LEGS=+1C270@5,-1C290@2"]).params).toEqual({ k: "350", type: "C", legs: "+1C270@5,-1C290@2" });
    expect(kvParams(["K=", "x"]).bad).toEqual(["K=", "x"]);
  });
});

describe("wordThenKv", () => {
  it("joins positional words under one key", () => {
    expect(wordThenKv(["CRUDE", "OIL"], "market").params).toEqual({ market: "CRUDE OIL" });
    expect(wordThenKv(["EURUSD", "R1=2", "R2=4"], "pair").params).toEqual({ pair: "EURUSD", r1: "2", r2: "4" });
  });
});

describe("ctArgs", () => {
  it("takes one futures root, upper-cased", () => {
    expect(ctArgs(["cl"])).toEqual({ params: { root: "CL" }, bad: [] });
    expect(ctArgs(["6e"]).params).toEqual({ root: "6E" });
    expect(ctArgs([])).toEqual({ params: {}, bad: [] });
  });
  it("reports a second word or a malformed root", () => {
    expect(ctArgs(["CL", "NG"]).bad).toEqual(["NG"]);
    expect(ctArgs(["CRUDE-OIL"]).bad).toEqual(["CRUDE-OIL"]);
  });
});

describe("fxfaArgs", () => {
  it("recognises the pair, the tenor list and R1/R2 by shape", () => {
    expect(fxfaArgs(["eurusd", "1w,1m", "r1=2", "R2=4"])).toEqual({ params: { pair: "EURUSD", tenors: "1W,1M", r1: "2", r2: "4" }, bad: [] });
    expect(fxfaArgs(["EUR/USD"]).params).toEqual({ pair: "EURUSD" });
  });
  it("reports anything else", () => {
    expect(fxfaArgs(["EURUSD", "X=1"]).bad).toEqual(["X=1"]);
    expect(fxfaArgs(["EURUSD", "GBPUSD"]).bad).toEqual(["GBPUSD"]);
  });
});
