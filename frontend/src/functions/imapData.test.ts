import { describe, expect, it } from "vitest";
import type { Universe, UniverseRow } from "./eqsFilter";
import { parseFilter } from "./eqsFilter";
import { buildImap, parseImapArgs } from "./imapData";

const U: Universe = {
  sectors: ["", "Technology", "Health Care", "Finance"],
  industries: ["", "Semiconductors", "Biotechnology", "Banks"],
  countries: ["", "United States", "China"],
  rows: [
    ["NVDA", "NVIDIA Corp", 180, 3.6, 2.04, 200e6, 4.4e12, 1, 1999, 1, 1],
    ["AMD", "Advanced Micro Devices", 160, -2, -1.2, 50e6, 2.6e11, 1, null, 1, 1],
    ["PFE", "Pfizer Inc", 28, 0.1, 0.36, 30e6, 1.6e11, 1, null, 2, 2],
    ["BABA", "Alibaba Group", 90, 1, 1.1, 10e6, 2.2e11, 2, 2014, 3, 3],
    ["NOCAP", "No Market Cap Inc", 5, 0, 0, 1e6, null, 1, null, 1, 1],
    ["ZEROCAP", "Zero Market Cap Inc", 5, 0, 0, 1e6, 0, 1, null, 1, 1],
    ["MYST", "Unclassified Co", 7, 0.1, 1, 1e6, 1e9, 1, null, 0, 0],
  ] as UniverseRow[],
};

describe("IMAP arguments", () => {
  it("grouping word, N=, and everything else goes to the EQS filter", () => {
    expect(parseImapArgs([])).toEqual({ by: "SECTOR", limit: 3000, rest: [] });
    expect(parseImapArgs(["industry", "MCAP>10B", "N=500"])).toEqual({ by: "INDUSTRY", limit: 500, rest: ["MCAP>10B"] });
    expect(parseImapArgs(["BY=COUNTRY"]).by).toBe("COUNTRY");
    expect(parseImapArgs(["N=999999"]).limit).toBe(5000);
    expect(parseImapArgs(["N=0"]).limit).toBe(3000);
    expect(parseImapArgs(["SECTOR=TECH", "COUNTRY"])).toEqual({ by: "COUNTRY", limit: 3000, rest: ["SECTOR=TECH"] });
  });
});

describe("IMAP data", () => {
  it("groups by sector, sizes by market cap, leaves out rows without one and says how many", () => {
    const r = buildImap(U, parseFilter([]), { by: "SECTOR", limit: 3000 });
    expect(r.groups.map((g) => g.key)).toEqual(["Technology", "Finance", "Health Care", "UNCLASSIFIED"]); // largest group first
    expect(r.groups[0].items.map((i) => r.rows[i.id][0])).toEqual(["NVDA", "AMD"]);
    expect(r.noCap).toBe(2);
    expect(r.rows).toHaveLength(5);
    expect(r.total).toBe(7);
    expect(r.groups[0].items[0].value).toBe(4.4e12);
  });

  it("filters with the EQS grammar before grouping", () => {
    const r = buildImap(U, parseFilter(["MCAP>200B"]), { by: "SECTOR", limit: 3000 });
    expect(r.groups.map((g) => g.key)).toEqual(["Technology", "Finance"]);
    expect(r.rows.map((x) => x[0]).sort()).toEqual(["AMD", "BABA", "NVDA"]);
  });

  it("groups by industry and by country", () => {
    expect(buildImap(U, parseFilter([]), { by: "INDUSTRY", limit: 3000 }).groups[0].key).toBe("Semiconductors");
    expect(buildImap(U, parseFilter([]), { by: "COUNTRY", limit: 3000 }).groups.map((g) => g.key)).toEqual(["United States", "China"]);
  });

  it("keeps the N largest by market cap", () => {
    const r = buildImap(U, parseFilter([]), { by: "SECTOR", limit: 2 });
    expect(r.rows.map((x) => x[0]).sort()).toEqual(["AMD", "NVDA"]);
    expect(r.cut).toBe(3);
  });

  it("an empty result is empty, not an error", () => {
    const r = buildImap(U, parseFilter(["MCAP>100T"]), { by: "SECTOR", limit: 10 });
    expect(r.groups).toEqual([]);
    expect(r.rows).toEqual([]);
  });
});
