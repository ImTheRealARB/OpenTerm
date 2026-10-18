import { describe, expect, it } from "vitest";
import { btStructure, lastOsa, osaStructure, rememberOsa } from "./optionsStructure";
import { parseBtArgs, isBtRun } from "./ruleParse";

const DATA = {
  sections: [
    { id: "legs", rows: [{ qty: 1, type: "C", strike: 270, premium: 5 }, { qty: -1, type: "C", strike: 290, premium: 2 }] },
    { id: "inputs", rows: [{ name: "R", value: "4.10%", rate: 0.041 }, { name: "MULT", value: "100" }] },
  ],
};

describe("OSA structure -> BT MKT=options", () => {
  it("reads legs, rate and multiplier from what OSA shows; expiry only from EXP=", () => {
    const s = osaStructure(DATA, ["STRAT=BULLCALL,270,290", "EXP=2026-12-18"])!;
    expect(s.legs).toEqual([
      { type: "call", strike: 270, qty: 1, expiry: "2026-12-18" },
      { type: "call", strike: 290, qty: -1, expiry: "2026-12-18" },
    ]);
    expect(s.risk_free_rate).toBe(0.041);
    expect(s.contract_multiplier).toBe(100);
    expect(osaStructure(DATA, ["T=0.5"])!.legs[0].expiry).toBeUndefined();
  });
  it("never invents fields: missing open, style and rate stay absent", () => {
    const s = osaStructure({ sections: [DATA.sections[0]] }, [])!;
    const out = btStructure(s, {});
    expect(Object.keys(out)).toEqual(["legs"]);
    expect(btStructure(s, { open: "2026-06-01", style: "european" })).toMatchObject({ open_date: "2026-06-01", exercise_style: "european" });
  });
  it("returns null without legs and remembers per symbol", () => {
    expect(osaStructure({ sections: [] }, [])).toBeNull();
    rememberOsa("aapl", osaStructure(DATA, [])!);
    expect(lastOsa("AAPL")?.legs).toHaveLength(2);
    rememberOsa("AAPL", null);
    expect(lastOsa("AAPL")).toBeUndefined();
  });
  it("BT parser: MKT=options needs no rule; OPEN/CLOSE/STYLE only with it", () => {
    const p = parseBtArgs(["AAPL", "MKT=options", "OPEN=2026-06-01", "STYLE=european"]);
    expect(isBtRun(p) && p.mkt === "options" && p.open === "2026-06-01" && p.style === "european").toBe(true);
    expect(parseBtArgs(["AAPL", "SMA20>SMA50", "OPEN=2026-06-01"]).ok).toBe(false);
    expect(parseBtArgs(["AAPL", "SMA20>SMA50", "MKT=options"]).ok).toBe(false);
    expect(parseBtArgs(["AAPL", "MKT=options", "OPEN=June"]).ok).toBe(false);
  });
});
