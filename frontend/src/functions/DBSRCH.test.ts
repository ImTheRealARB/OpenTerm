import { describe, expect, it } from "vitest";
import { buildDbsrchArgs, count, DATASET_PAGE, hasNext, pageText, parseDbsrchArgs, prevOffset, SERIES_PAGE } from "./dbsrchArgs";
import { FUNCTIONS } from "./registry";
import { parseEcstArgs } from "./worldArgs";

describe("DBSRCH registry entry", () => {
  it("is registered with a loader and no security", () => {
    const def = FUNCTIONS.get("DBSRCH");
    expect(def).toBeDefined();
    expect(def?.load).toBeTypeOf("function");
    expect(def?.needsSecurity).toBe(false);
  });
});

describe("DBSRCH arguments", () => {
  it("treats plain words as the dataset search", () => {
    expect(parseDbsrchArgs(["france", "inflation"])).toEqual({ q: "france inflation", dataset: "", offset: 0, error: null });
    expect(parseDbsrchArgs(["OECD", "unemployment"]).q).toBe("OECD unemployment");
  });

  it("reads DS: and OFFSET: wherever they stand among the words", () => {
    const p = parseDbsrchArgs(["france", "DS:bdf/ICP", "inflation", "OFFSET:30"]);
    expect(p).toEqual({ q: "france inflation", dataset: "BDF/ICP", offset: 30, error: null });
  });

  it("keeps the dataset code exactly as typed (Eurostat codes are lower case, OECD codes hold @)", () => {
    expect(parseDbsrchArgs(["DS:eurostat/une_rt_m"]).dataset).toBe("EUROSTAT/une_rt_m");
    expect(parseDbsrchArgs(["DS:OECD/DSD_TAXBEN_NRR@DF_NRR", "france"]).dataset).toBe("OECD/DSD_TAXBEN_NRR@DF_NRR");
  });

  it("lets a series list go without words but asks for words for the dataset search", () => {
    expect(parseDbsrchArgs(["DS:ECB/CSEC"]).error).toBeNull();
    expect(parseDbsrchArgs([]).error).toMatch(/GIVE SEARCH WORDS/);
    expect(parseDbsrchArgs(["a"]).error).toMatch(/GIVE SEARCH WORDS/);
    expect(parseDbsrchArgs(["DS:ECB/CSEC", "x"]).error).toMatch(/2\+ CHARACTERS/);
  });

  it("a malformed DS: token is just a word, not a dataset", () => {
    const p = parseDbsrchArgs(["DS:nonsense"]);
    expect(p.dataset).toBe("");
    expect(p.q).toBe("DS:nonsense");
  });

  it("builds args that parse back to the same state", () => {
    for (const s of [
      { q: "france inflation", dataset: "", offset: 0 },
      { q: "france inflation", dataset: "BDF/ICP", offset: 60 },
      { q: "", dataset: "ECB/CSEC", offset: 0 },
    ]) {
      const back = parseDbsrchArgs(buildDbsrchArgs(s));
      expect(back).toEqual({ ...s, error: null });
    }
    expect(buildDbsrchArgs({ q: "gdp", dataset: "", offset: 0 })).toEqual(["gdp"]);
  });

  it("hands ECST an id that ECST accepts, including OECD datasets with @", () => {
    expect(parseEcstArgs(["DBN:OECD/DSD_TAXBEN_NRR@DF_NRR/AUS.NHIDU.A"]).error).toBeNull();
    expect(parseEcstArgs(["DBN:BDF/ICP/A.AT.N.000000.4.INW"]).error).toBeNull();
  });
});

describe("DBSRCH paging and counts", () => {
  it("describes the page, or says NO MATCH", () => {
    expect(pageText(0, 20, 90)).toBe("1-20 OF 90");
    expect(pageText(40, 20, 90)).toBe("41-60 OF 90");
    expect(pageText(0, 0, 0)).toBe("NO MATCH");
  });

  it("knows when a next page exists", () => {
    expect(hasNext(0, DATASET_PAGE, 90)).toBe(true);
    expect(hasNext(80, 10, 90)).toBe(false);
    expect(hasNext(0, 0, 0)).toBe(false);
  });

  it("steps back a page but never below the first", () => {
    expect(prevOffset(0, SERIES_PAGE)).toBeNull();
    expect(prevOffset(30, SERIES_PAGE)).toBe(0);
    expect(prevOffset(10, SERIES_PAGE)).toBe(0);
    expect(prevOffset(60, SERIES_PAGE)).toBe(30);
  });

  it("leaves an unknown count blank", () => {
    expect(count(null)).toBe("");
    expect(count(undefined)).toBe("");
    expect(count(275520)).toBe("275,520");
  });
});
