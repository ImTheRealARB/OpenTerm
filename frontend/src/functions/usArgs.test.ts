import { describe, expect, it } from "vitest";
import { fmtChange, fmtNum, fmtSigned, fmtUsd, parseTradeArgs, parseUsmacArgs, signColor } from "./usArgs";

describe("TRADE arguments", () => {
  it("needs a reporter", () => {
    expect(parseTradeArgs([]).error).toMatch(/USAGE/);
  });
  it("tells partner, product and years apart by shape", () => {
    expect(parseTradeArgs(["usa", "chn", "8517", "8y"])).toMatchObject({ reporter: "USA", partner: "CHN", hs: "8517", years: 8, error: null });
    expect(parseTradeArgs(["usa", "85"])).toMatchObject({ partner: "", hs: "85", years: 5 });
    expect(parseTradeArgs(["usa", "world", "total"])).toMatchObject({ partner: "WORLD", hs: "TOTAL" });
  });
  it("rejects a second partner and a silly year count", () => {
    expect(parseTradeArgs(["usa", "chn", "ind"]).error).toMatch(/CANNOT READ IND/);
    expect(parseTradeArgs(["usa", "chn", "20Y"]).error).toMatch(/1Y TO 12Y/);
  });
});

describe("USMAC arguments", () => {
  it("defaults to the BLS board", () => {
    expect(parseUsmacArgs([])).toMatchObject({ src: "BLS", q: "", single: false, years: 3 });
  });
  it("one BLS series opens its history over ten years", () => {
    expect(parseUsmacArgs(["bls", "cpi"])).toMatchObject({ src: "BLS", q: "CPI", single: true, years: 10 });
    expect(parseUsmacArgs(["BLS", "CPI", "UNEMP"]).single).toBe(false);
  });
  it("BEA industry is a board, other BEA tables are histories; Census is always a board", () => {
    expect(parseUsmacArgs(["BEA", "GDPG"]).single).toBe(true);
    expect(parseUsmacArgs(["BEA", "INDUSTRY"]).single).toBe(false);
    expect(parseUsmacArgs(["CENSUS", "TRADE", "CHINA", "85"])).toMatchObject({ src: "CENSUS", q: "TRADE CHINA 85", single: false });
  });
  it("flags a misspelled source", () => {
    expect(parseUsmacArgs(["BLSX", "CPI"]).error).toMatch(/UNKNOWN SOURCE/);
  });
});

describe("number formats", () => {
  it("keeps small numbers precise and shortens big ones", () => {
    expect(fmtNum(4.3)).toBe("4.30");
    expect(fmtNum(1234567.8)).toBe("1,234,568");
    expect(fmtNum(null)).toBe("");
    expect(fmtSigned(0.5)).toBe("+0.50");
    expect(fmtUsd(1.2e11)).toBe("120.00B");
    expect(fmtUsd(5.5e8)).toBe("550.0M");
    expect(fmtUsd(null)).toBe("");
  });
  it("writes a change per kind: percent for amounts, percentage points for rates, nothing guessed when unknown", () => {
    expect(fmtChange("level", 3, 1)).toEqual({ chg: "+3.00", pct: "+1.00%" });
    // 2.2 -> 3.4 is +1.2 percentage points, never "+54.55%": a percent of a percentage misleads
    expect(fmtChange("rate", 1.2, 54.545)).toEqual({ chg: "+1.20 pp", pct: "" });
    expect(fmtChange("rate", -0.3, null)).toEqual({ chg: "-0.30 pp", pct: "" });
    expect(fmtChange("unknown", 1.2, 54.545)).toEqual({ chg: "+1.20", pct: "" });
    expect(fmtChange("level", null, null)).toEqual({ chg: "", pct: "" });
  });
  it("colours by sign", () => {
    expect([signColor(1), signColor(-1), signColor(0), signColor(null)]).toEqual(["up", "down", "dim", "dim"]);
  });
});
