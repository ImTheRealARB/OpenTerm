import { describe, expect, it } from "vitest";
import { glossaryColumns, termForColumn } from "./gridTips";
import { GLOSSARY } from "./glossary";

describe("termForColumn", () => {
  it("maps common headers to glossary terms", () => {
    expect(termForColumn("P/E")).toBe("P/E");
    expect(termForColumn("MKT CAP")).toBe("MARKET CAP");
    expect(termForColumn("CHG%")).toBe("CHANGE");
    expect(termForColumn("%chg")).toBe("CHANGE");
    expect(termForColumn("LAST")).toBe("LAST");
    expect(termForColumn("YLD")).toBe("YIELD");
  });
  it("is empty for headers without an entry", () => {
    expect(termForColumn("NAME")).toBe("");
    expect(termForColumn("SRC")).toBe("");
  });
  it("lists the columns that have a tip", () => {
    expect(glossaryColumns(["SYMBOL", "NAME", "LAST", "%CHG", "VOLUME", "MKT CAP"])).toEqual([2, 3, 4, 5]);
  });
  it("every alias points at a real glossary entry", () => {
    for (const t of ["MKT CAP", "VOL", "YLD", "DIV YLD", "ADJ CLOSE", "MAX DD", "B - A", "1Y RANGE", "UNRL %", "WIN", "MKT VAL", "DAY CHG", "24H LOW", "PRICE", "CHANGE %"]) {
      expect(GLOSSARY[termForColumn(t)], t).toBeTruthy();
    }
  });
});
