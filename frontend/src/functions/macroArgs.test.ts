import { describe, expect, it } from "vitest";
import {
  addDays, bpChange, curveShape, dayLabel, fmtBp, fmtSeriesChange, fmtSeriesValue, fredIdForTenor, isIsoDate, isWeekend,
  nyToday, parseEcoArgs, parseErnArgs, parseFredArgs, parseMacroArgs, spreadBp, yieldBar,
} from "./macroArgs";

describe("parseFredArgs", () => {
  it("takes the series and an optional range in any order", () => {
    expect(parseFredArgs(["unrate"])).toEqual({ id: "UNRATE", range: "5Y", ignored: [] });
    expect(parseFredArgs(["dgs10", "10y"])).toEqual({ id: "DGS10", range: "10Y", ignored: [] });
    expect(parseFredArgs(["max", "T10Y2Y"])).toEqual({ id: "T10Y2Y", range: "MAX", ignored: [] });
  });
  it("reports a missing series and keeps stray tokens visible", () => {
    expect(parseFredArgs([]).id).toBeNull();
    expect(parseFredArgs(["5y"]).id).toBeNull();
    expect(parseFredArgs(["GDP", "CPIAUCSL", "bad id!"]).ignored).toEqual(["CPIAUCSL", "BAD ID!"]);
  });
});

describe("parseMacroArgs", () => {
  it("joins and trims the query", () => expect(parseMacroArgs(["  consumer", "price "])).toBe("consumer price"));
});

describe("dates", () => {
  it("validates real calendar days only", () => {
    expect(isIsoDate("2026-10-17")).toBe(true);
    expect(isIsoDate("2026-02-30")).toBe(false);
    expect(isIsoDate("17/10/2026")).toBe(false);
  });
  it("adds days across month and year ends", () => {
    expect(addDays("2026-10-31", 1)).toBe("2026-11-01");
    expect(addDays("2026-01-01", -1)).toBe("2025-12-31");
    expect(addDays("2024-02-28", 1)).toBe("2024-02-29");
  });
  it("labels days and finds weekends", () => {
    expect(dayLabel("2026-10-16")).toBe("FRI 16 OCT 2026");
    expect(isWeekend("2026-10-17")).toBe(true);
    expect(isWeekend("2026-10-16")).toBe(false);
  });
  it("reads the New York day, not the UTC day", () => {
    expect(nyToday(new Date("2026-10-17T02:30:00Z"))).toBe("2026-10-16");
    expect(nyToday(new Date("2026-10-17T18:00:00Z"))).toBe("2026-10-17");
  });
});

describe("parseErnArgs", () => {
  const today = "2026-10-16";
  it("understands words, offsets and ISO dates", () => {
    expect(parseErnArgs([], today)).toEqual({ ok: true, date: today });
    expect(parseErnArgs(["tomorrow"], today)).toEqual({ ok: true, date: "2026-10-17" });
    expect(parseErnArgs(["-3"], today)).toEqual({ ok: true, date: "2026-10-13" });
    expect(parseErnArgs(["+10"], today)).toEqual({ ok: true, date: "2026-10-26" });
    expect(parseErnArgs(["2026-11-02"], today)).toEqual({ ok: true, date: "2026-11-02" });
  });
  it("rejects anything else with the usage line", () => {
    const r = parseErnArgs(["next"], today);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toContain("USE ERN");
  });
});

describe("parseEcoArgs", () => {
  it("defaults to 14 days", () => expect(parseEcoArgs([])).toEqual({ days: 14, major: false, start: null, error: null }));
  it("reads window, MAJOR and start in any order", () => {
    expect(parseEcoArgs(["major", "30d", "2026-11-01"])).toEqual({ days: 30, major: true, start: "2026-11-01", error: null });
    expect(parseEcoArgs(["7"]).days).toBe(7);
  });
  it("flags unknown words and out-of-range windows", () => {
    expect(parseEcoArgs(["soon"]).error).toContain("BAD ARGUMENT SOON");
    expect(parseEcoArgs(["99"]).error).toContain("BAD ARGUMENT 99");
  });
});

describe("curve math", () => {
  const tenors = ["3M", "2Y", "10Y", "30Y"];
  const y = [4.2, 4.35, 4.7, null];
  it("computes spreads in basis points", () => {
    expect(spreadBp(tenors, y, "2Y", "10Y")).toBe(35);
    expect(spreadBp(tenors, y, "3M", "10Y")).toBe(50);
    expect(spreadBp(tenors, y, "2Y", "30Y")).toBeNull();
    expect(spreadBp(tenors, y, "2Y", "5Y")).toBeNull();
  });
  it("rounds away float noise", () => expect(spreadBp(["2Y", "10Y"], [4.1, 4.25], "2Y", "10Y")).toBe(15));
  it("changes and formatting", () => {
    expect(bpChange(4.35, 4.28)).toBe(7);
    expect(bpChange(null, 4.28)).toBeNull();
    expect(fmtBp(7)).toBe("+7");
    expect(fmtBp(-12)).toBe("-12");
    expect(fmtBp(null)).toBe("-");
  });
  it("shapes", () => {
    expect(curveShape(-5)).toBe("INVERTED");
    expect(curveShape(5)).toBe("FLAT");
    expect(curveShape(35)).toBe("NORMAL");
    expect(curveShape(null)).toBeNull();
  });
  it("maps tenors to FRED ids where FRED has them", () => {
    expect(fredIdForTenor("10Y")).toBe("DGS10");
    expect(fredIdForTenor("3M")).toBe("DGS3MO");
    expect(fredIdForTenor("1.5M")).toBeNull();
  });
  it("scales bars", () => {
    expect(yieldBar(5, 5, 10)).toBe("█".repeat(10));
    expect(yieldBar(0.01, 5, 10)).toBe("█");
    expect(yieldBar(null, 5, 10)).toBe("");
  });
});

describe("series values", () => {
  it("picks decimals by size", () => {
    expect(fmtSeriesValue(4.2)).toBe("4.20");
    expect(fmtSeriesValue(32563.03)).toBe("32,563.0");
    expect(fmtSeriesValue(7100000)).toBe("7,100,000");
    expect(fmtSeriesValue(0.0012)).toBe("0.0012");
    expect(fmtSeriesValue(null)).toBe("-");
  });
  it("signs changes", () => {
    expect(fmtSeriesChange(0.1)).toBe("+0.10");
    expect(fmtSeriesChange(-2)).toBe("-2.00");
  });
});
