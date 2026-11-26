import { describe, expect, it } from "vitest";
import { compact, parseBioArgs, parseEsgArgs, parseFtsArgs, parseMaArgs, splitWords } from "./filingsArgs";
import { FUNCTIONS } from "./registry";

describe("Phase 29 filings functions are registered", () => {
  it.each(["FTS", "MA", "LEGAL", "BIO", "RELS", "ESG"])("%s has a loader", (code) => {
    expect(FUNCTIONS.get(code)?.load).toBeTypeOf("function");
  });
});

describe("FTS arguments", () => {
  it("puts the quoted words back together and reads KEY=value and a trailing ticker", () => {
    const a = parseFtsArgs(['"going', 'concern"', "FORM=10-K", "FROM=2024-01-01", "TO=2024-12-31", "AAPL"]);
    expect(a).toEqual({ q: "going concern", forms: "10-K", start: "2024-01-01", end: "2024-12-31", symbol: "AAPL" });
  });
  it("without quotes every bare word is search text and CO= names the company", () => {
    expect(parseFtsArgs(["material", "weakness", "CO=msft"])).toMatchObject({ q: "material weakness", symbol: "MSFT" });
  });
  it("drops a stray quote and empty parameters", () => {
    expect(splitWords(['"ab', "cd"]).words.join(" ")).toBe("ab cd");
    expect(compact({ q: "x", forms: "" })).toEqual({ q: "x" });
  });
});

describe("MA, BIO and ESG arguments", () => {
  it("MA: no symbol means market-wide; a symbol or the panel security is one company", () => {
    expect(parseMaArgs([])).toEqual({ symbol: "", start: "", end: "" });
    expect(parseMaArgs(["FROM=2024-10-01", "aapl"])).toEqual({ symbol: "AAPL", start: "2024-10-01", end: "" });
    expect(parseMaArgs([], "NKE").symbol).toBe("NKE");
  });
  it("BIO: a CIK or a quoted name", () => {
    expect(parseBioArgs(["1214156"]).q).toBe("1214156");
    expect(parseBioArgs(['"COOK', 'TIMOTHY"']).q).toBe("COOK TIMOTHY");
  });
  it("ESG: symbol, year and a NAME= override", () => {
    expect(parseEsgArgs(["AA", "YEAR=2022"], undefined)).toEqual({ symbol: "AA", name: "", year: "2022" });
    expect(parseEsgArgs(['NAME="exxon', 'mobil"'], undefined).name).toBe("exxon mobil");
  });
});
