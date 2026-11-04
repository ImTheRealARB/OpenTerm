import { describe, expect, it } from "vitest";
import { parseCommand } from "./parser";
import { mapSector, parseSector } from "./sectors";

// A tiny function table, like parser.test.ts. FX is a function code on purpose (see the clash test).
const FNS = new Set(["GP", "DES", "FX", "HELP"]);
const p = (s: string) => parseCommand(s, (c) => FNS.has(c));

describe("sector words in the command grammar", () => {
  it("maps the examples from the spec", () => {
    expect(p("SPX INDEX GP")).toMatchObject({ ok: true, security: { symbol: "^GSPC" }, fn: "GP" });
    expect(p("EURUSD CURNCY GP")).toMatchObject({ ok: true, security: { symbol: "EURUSD=X" }, fn: "GP" });
    expect(p("CL1 COMDTY GP")).toMatchObject({ ok: true, security: { symbol: "CL=F" }, fn: "GP" });
    expect(p("AAPL US EQUITY GP")).toMatchObject({ ok: true, security: { symbol: "AAPL" }, fn: "GP" });
    expect(p("US10Y GOVT GP")).toMatchObject({ ok: true, security: { symbol: "^TNX" }, fn: "GP" });
  });
  it("is case-insensitive and accepts short forms", () => {
    expect(p("spx idx gp")).toMatchObject({ security: { symbol: "^GSPC" }, fn: "GP" });
    expect(p("aapl eq des")).toMatchObject({ security: { symbol: "AAPL" }, fn: "DES" });
    expect(p("eurusd ccy gp")).toMatchObject({ security: { symbol: "EURUSD=X" } });
    expect(p("co1 cmd gp")).toMatchObject({ security: { symbol: "BZ=F" } });
  });
  it("EQUITY keeps the market suffix", () => {
    expect(p("RELIANCE IN EQUITY GP")).toMatchObject({ security: { symbol: "RELIANCE.NS" }, fn: "GP" });
  });
  it("works without a function (sector only)", () => {
    expect(p("SPX INDEX")).toMatchObject({ ok: true, security: { symbol: "^GSPC" }, args: [] });
    expect(p("SPX INDEX")).not.toHaveProperty("fn");
  });
  it("keeps args after the function", () => {
    expect(p("SPX INDEX GP 1Y")).toMatchObject({ fn: "GP", args: ["1Y"] });
  });
  it("GOVT and CORP without a free source give a clear error", () => {
    expect(p("DE10Y GOVT GP")).toMatchObject({ ok: false, error: expect.stringContaining("GOVT") });
    expect(p("IBM CORP GP")).toMatchObject({ ok: false, error: expect.stringContaining("CORP") });
  });
  it("a function code with the same letters as a sector word still wins", () => {
    // FX is a function here, so "EURUSD FX" is the FX function, not a sector.
    expect(p("EURUSD FX")).toMatchObject({ ok: true, security: { symbol: "EURUSD" }, fn: "FX" });
  });
  it("old grammar still works", () => {
    expect(p("AAPL GP")).toMatchObject({ security: { symbol: "AAPL" }, fn: "GP" });
    expect(p("AAPL US GP")).toMatchObject({ security: { symbol: "AAPL" }, fn: "GP" });
    expect(p("AAPL NOPE")).toMatchObject({ ok: false });
  });
});

describe("mapSector", () => {
  it("passes provider symbols through", () => {
    expect(mapSector("INDEX", "^DJI")).toEqual({ ok: true, symbol: "^DJI" });
    expect(mapSector("CURNCY", "JPY=X")).toEqual({ ok: true, symbol: "JPY=X" });
    expect(mapSector("COMDTY", "GC=F")).toEqual({ ok: true, symbol: "GC=F" });
  });
  it("guesses sensible forms", () => {
    expect(mapSector("INDEX", "FOO")).toEqual({ ok: true, symbol: "^FOO" });
    expect(mapSector("CURNCY", "JPY")).toEqual({ ok: true, symbol: "JPY=X" });
    expect(mapSector("CURNCY", "EU")).toMatchObject({ ok: false });
    expect(mapSector("COMDTY", "NG1")).toEqual({ ok: true, symbol: "NG=F" });
  });
  it("parseSector ignores other words", () => {
    expect(parseSector("GP")).toBeUndefined();
    expect(parseSector(undefined)).toBeUndefined();
    expect(parseSector("govt")).toBe("GOVT");
  });
});
