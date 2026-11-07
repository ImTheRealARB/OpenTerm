import { describe, expect, it } from "vitest";
import type { WecoRow } from "../net/types";
import { fmtCell, fmtStat, parseEcstArgs, sortWeco } from "./worldArgs";

describe("ECST arguments", () => {
  it("country then indicator, several-word countries, case folded", () => {
    expect(parseEcstArgs(["usa", "cpi"])).toEqual({ country: "usa", ind: "CPI", error: null });
    expect(parseEcstArgs(["South", "Korea", "gdp"])).toEqual({ country: "South Korea", ind: "GDP", error: null });
  });
  it("a DBnomics reference stands alone or after anything", () => {
    expect(parseEcstArgs(["DBN:IMF/WEO:latest/USA.NGDP_RPCH"])).toEqual({ country: "", ind: "DBN:IMF/WEO:latest/USA.NGDP_RPCH", error: null });
    expect(parseEcstArgs(["x", "dbn:eurostat/une_rt_m/M.SA.TOTAL.PC_ACT.T.EA20"]).ind).toBe("dbn:eurostat/une_rt_m/M.SA.TOTAL.PC_ACT.T.EA20");
  });
  it("missing pieces say what to type", () => {
    expect(parseEcstArgs([]).error).toContain("USAGE: ECST");
    expect(parseEcstArgs(["cpi"]).error).toContain("GIVE A COUNTRY");
    expect(parseEcstArgs(["usa"]).error).toContain("GIVE AN INDICATOR");
    expect(parseEcstArgs(["usa", "banana"]).error).toContain("GIVE AN INDICATOR");
  });
});

const row = (name: string, a: number | null, b: number | null): WecoRow => ({
  iso3: name.slice(0, 3).toUpperCase(), name,
  cells: { GDPG: a == null ? null : { v: a, year: 2025, stale: false }, CPI: b == null ? null : { v: b, year: 2024, stale: false } },
});

describe("WECO sorting and cells", () => {
  const rows = [row("Brazil", 2, 5), row("Argentina", null, 220), row("Chile", 3, null), row("Denmark", 1, 2)];
  it("sorts a column both ways with empty cells last", () => {
    expect(sortWeco(rows, ["GDPG", "CPI"], 0, true).map((r) => r.name)).toEqual(["Chile", "Brazil", "Denmark", "Argentina"]);
    expect(sortWeco(rows, ["GDPG", "CPI"], 0, false).map((r) => r.name)).toEqual(["Denmark", "Brazil", "Chile", "Argentina"]);
    expect(sortWeco(rows, ["GDPG", "CPI"], 1, true).map((r) => r.name)).toEqual(["Argentina", "Brazil", "Denmark", "Chile"]);
  });
  it("sorts by name", () => {
    expect(sortWeco(rows, ["GDPG", "CPI"], "name", false).map((r) => r.name)).toEqual(["Argentina", "Brazil", "Chile", "Denmark"]);
  });
  it("a cell always shows its own year", () => {
    expect(fmtCell(rows[0].cells.GDPG)).toBe("2.0 (2025)");
    expect(fmtCell(rows[1].cells.CPI)).toBe("220 (2024)");
    expect(fmtCell(null)).toBe("");
  });
  it("big values get suffixes", () => {
    expect(fmtStat(2.9e13, "US$")).toBe("29.00T");
    expect(fmtStat(3.4e8, "people")).toBe("340.00M");
    expect(fmtStat(2.16, "%")).toBe("2.16");
    expect(fmtStat(null, "%")).toBe("");
  });
});
