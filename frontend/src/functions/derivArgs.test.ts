import { describe, expect, it } from "vitest";
import { kvParams, omonArgs, wordThenKv } from "./derivArgs";

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
