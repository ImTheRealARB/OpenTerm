import { describe, expect, it } from "vitest";
import { ALIASES, TWINS } from "./aliases";
import { FUNCTIONS, FUNCTION_LIST, relatedCodes, showsSecurity } from "./registry";

// These pin the per-function flags that used to be copied as code lists in Panel, TabStrip, CommandLine and windowMenu.
describe("registry flags", () => {
  it("shows the security in a title only for functions that use it", () => {
    expect(showsSecurity({ fn: "GP", args: ["1Y"] })).toBe(true);
    expect(showsSecurity({ fn: "FA", args: [] })).toBe(true);
    expect(showsSecurity({ fn: "WEI", args: [] })).toBe(false);
    expect(showsSecurity({ args: [] })).toBe(false); // empty panel
    expect(showsSecurity({ fn: "NOPE", args: [] })).toBe(false); // unknown code
  });

  it("treats bare N as using the security, but N with arguments as not", () => {
    expect(showsSecurity({ fn: "N", args: [] })).toBe(true);
    expect(showsSecurity({ fn: "N", args: ["TOP"] })).toBe(false);
  });

  it("prefetches only GP and BT while typing", () => {
    expect(FUNCTION_LIST.filter((f) => f.prefetchOnType).map((f) => f.code).sort()).toEqual(["BT", "GP"]);
  });

  it("skips the GUI quote strip only for DES and QR", () => {
    expect(FUNCTION_LIST.filter((f) => f.leadsWithPrice).map((f) => f.code).sort()).toEqual(["DES", "QR"]);
  });

  it("keeps the RELATED window menu lists in their original order", () => {
    expect(relatedCodes(true)).toEqual(["DES", "GP", "QR", "FA", "N", "HDS", "OWN", "COMP", "DVD", "EE", "ANR", "OMON"]);
    expect(relatedCodes(false)).toEqual(["WEI", "MOV", "FX", "CMDTY", "CRYP", "RATES", "ECO", "N"]);
  });

  it("gives each RELATED rank to one function only", () => {
    for (const kind of ["security", "market"] as const) {
      const ranks = FUNCTION_LIST.map((f) => f.related?.[kind]).filter((r) => r !== undefined);
      expect(new Set(ranks).size, kind).toBe(ranks.length);
    }
  });
});

describe("twins and aliases", () => {
  it("a twin has its own registry entry and keeps its own code; an alias has none and resolves to the original", () => {
    for (const [twin, original] of Object.entries(TWINS)) {
      expect(FUNCTIONS.get(twin)?.code, twin).toBe(twin);
      expect(FUNCTIONS.get(original)?.code, original).toBe(original);
    }
    for (const [alias, target] of Object.entries(ALIASES)) {
      expect(FUNCTION_LIST.some((f) => f.code === alias), alias).toBe(false);
      expect(FUNCTIONS.get(alias)?.code, alias).toBe(target);
    }
  });

  it("no word is both a twin and an alias", () => {
    for (const t of Object.keys(TWINS)) expect(ALIASES[t], t).toBeUndefined();
  });
});
