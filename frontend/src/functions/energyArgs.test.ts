import { describe, expect, it } from "vitest";
import type { NrgRow, WxAlert } from "../net/api";
import { alertColor, alertLine, fmtDd, fmtPrice, fmtSigned, fmtTemp, nrgChg, parseNrgArgs, placeArg, posBar } from "./energyArgs";

describe("parseNrgArgs", () => {
  it("empty = the board", () => expect(parseNrgArgs([])).toEqual({ id: null, error: null }));
  it("resolves aliases and FRED ids, any case", () => {
    expect(parseNrgArgs(["wti"]).id).toBe("DCOILWTICO");
    expect(parseNrgArgs(["HH"]).id).toBe("DHHNGSP");
    expect(parseNrgArgs(["dgasnyh"]).id).toBe("DGASNYH");
  });
  it("refuses an unknown series and lists the choices", () => {
    const r = parseNrgArgs(["WCESTUS1"]);
    expect(r.id).toBeNull();
    expect(r.error).toContain("UNKNOWN ENERGY SERIES WCESTUS1");
    expect(r.error).toContain("BRENT");
  });
});

describe("formats", () => {
  it("prices use the unit's decimals", () => {
    expect(fmtPrice(81.956, "$/BBL")).toBe("81.96");
    expect(fmtPrice(2.7849, "$/MMBTU")).toBe("2.785");
    expect(fmtPrice(null, "$/GAL")).toBe("");
  });
  it("signed changes", () => {
    expect(fmtSigned(1.234, 2)).toBe("+1.23");
    expect(fmtSigned(-0.5, 1)).toBe("-0.5");
    expect(fmtSigned(0, 2)).toBe("0.00");
  });
  it("position bar is ten cells and clamps", () => {
    expect(posBar(50)).toBe("#####.....");
    expect(posBar(0)).toBe("..........");
    expect(posBar(100)).toBe("##########");
    expect(posBar(140)).toBe("##########");
    expect(posBar(null)).toBe("");
  });
  it("change colour", () => {
    const row = (chg: number | null) => ({ chg }) as NrgRow;
    expect([nrgChg(row(1)), nrgChg(row(-1)), nrgChg(row(0)), nrgChg(row(null))]).toEqual(["up", "down", "dim", "dim"]);
  });
  it("temperatures and degree days", () => {
    expect(fmtTemp(8.24)).toBe("8.2C");
    expect(fmtTemp(null)).toBe("");
    expect(fmtDd(12.34)).toBe("12.3");
  });
});

describe("WETR place and alerts", () => {
  it("joins words", () => {
    expect(placeArg(["new", "york"])).toBe("new york");
    expect(placeArg(["29.76,-95.37"])).toBe("29.76,-95.37");
    expect(placeArg([])).toBe("");
  });
  const alert = (severity: string): WxAlert => ({ event: "Flood Warning", severity, urgency: null, area: "Harris, TX", headline: null, onset: null, ends: "2026-10-18T20:15:00-05:00" });
  it("severity colours and line", () => {
    expect(alertColor(alert("Severe"))).toBe("err");
    expect(alertColor(alert("Moderate"))).toBe("warn");
    expect(alertColor(alert("Unknown"))).toBe("dim");
    expect(alertLine(alert("Severe"))).toBe("SEVERE · FLOOD WARNING · HARRIS, TX UNTIL 2026-10-18 20:15");
  });
});
