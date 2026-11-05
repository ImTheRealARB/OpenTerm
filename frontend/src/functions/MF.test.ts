import { describe, expect, it } from "vitest";
import { fmtNav, fmtPct, isoOfEpoch, MF_USAGE, navAgeDays, navAgeText, parseMfArgs, searchHeadline } from "./mfArgs";
import { FUNCTIONS } from "./registry";

describe("MF registry entry", () => {
  it("is registered with a loader and no security", () => {
    const def = FUNCTIONS.get("MF");
    expect(def).toBeDefined();
    expect(def?.load).toBeTypeOf("function");
    expect(def?.needsSecurity).toBe(false);
  });
});

describe("MF arguments", () => {
  it("treats words as a scheme-name search", () => {
    expect(parseMfArgs(["parag", "parikh"])).toEqual({ kind: "search", q: "parag parikh", error: null });
    expect(parseMfArgs(["  Nifty ", "", "index"]).q).toBe("Nifty index");
  });

  it("treats 4 to 7 digits as a scheme code and drops leading zeros", () => {
    expect(parseMfArgs(["122639"])).toEqual({ kind: "fund", q: "122639", error: null });
    expect(parseMfArgs(["0122639"]).q).toBe("122639");
  });

  it("refuses a number that cannot be a scheme code instead of searching for it", () => {
    expect(parseMfArgs(["12"]).error).toContain("5 OR 6 DIGITS");
    expect(parseMfArgs(["123456789"]).error).toContain("5 OR 6 DIGITS");
  });

  it("asks for words when there are none or they are too short", () => {
    expect(parseMfArgs([]).error).toContain(MF_USAGE);
    expect(parseMfArgs(["ab"]).error).toContain(MF_USAGE);
  });
});

describe("MF formatting", () => {
  it("signs returns and shows a dash, never a number, when there is none", () => {
    expect(fmtPct(1.0749)).toBe("+1.07%");
    expect(fmtPct(-3.4)).toBe("-3.40%");
    expect(fmtPct(0)).toBe("0.00%");
    expect(fmtPct(null)).toBe("-");
    expect(fmtPct(Number.NaN)).toBe("-");
  });

  it("shows NAV to four decimals", () => {
    expect(fmtNav(90.7043)).toBe("90.7043");
    expect(fmtNav(10)).toBe("10.0000");
    expect(fmtNav(null)).toBe("-");
  });

  it("counts NAV age in whole UTC days", () => {
    const noon = Date.UTC(2026, 10, 5, 12, 0, 0); // 2026-11-05 12:00 UTC
    expect(navAgeDays("2026-11-05", noon)).toBe(0);
    expect(navAgeDays("2026-11-03", noon)).toBe(2);
    expect(navAgeDays("2026-11-07", noon)).toBe(0); // a date in the future never reads as negative
    expect(navAgeText(0)).toBe("TODAY");
    expect(navAgeText(1)).toBe("1 DAY OLD");
    expect(navAgeText(5)).toBe("5 DAYS OLD");
  });

  it("turns chart timestamps back into the NAV dates", () => {
    expect(isoOfEpoch(1793664000)).toBe("2026-11-03");
  });

  it("describes the search result, including a cut list and no match", () => {
    expect(searchHeadline(15, 15, "parag parikh")).toBe('15 SCHEMES MATCH "PARAG PARIKH"');
    expect(searchHeadline(1, 1, "x")).toBe('1 SCHEME MATCH "X"');
    expect(searchHeadline(612, 200, "nifty")).toContain("FIRST 200 OF 612");
    expect(searchHeadline(0, 0, "zzz")).toContain("NO SCHEME NAME HAS ALL THE WORDS");
  });
});
