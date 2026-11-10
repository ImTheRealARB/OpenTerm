import { describe, expect, it } from "vitest";
import { fmtDur, fmtMoney, fmtPct, importBody, mappingToText, nextOf, parseArgs, textToMapping } from "./journalModel";

describe("JRNL arguments", () => {
  it("takes a view and a currency in any order", () => {
    expect(parseArgs([])).toEqual({ view: "TRIPS", currency: undefined });
    expect(parseArgs(["eur", "findings"])).toEqual({ view: "FINDINGS", currency: "EUR" });
    expect(parseArgs(["shadow"]).view).toBe("SHADOW");
  });
  it("names an unknown argument", () => {
    expect(parseArgs(["FOO12"]).bad).toBe("UNKNOWN ARGUMENT FOO12");
    expect(parseArgs(["USD", "EUR"]).bad).toBe("UNKNOWN ARGUMENT EUR");
  });
});

describe("JRNL formats", () => {
  it("never invents a number", () => {
    expect(fmtMoney(null)).toBe("-");
    expect(fmtMoney(NaN)).toBe("-");
    expect(fmtPct(undefined)).toBe("-");
    expect(fmtDur(null)).toBe("-");
  });
  it("formats money, percent and durations", () => {
    expect(fmtMoney(-1234.5)).toBe("-1,234.50");
    expect(fmtPct(0.4567)).toBe("45.7%");
    expect([fmtDur(30), fmtDur(600), fmtDur(7200), fmtDur(259200)]).toEqual(["30s", "10m", "2.0h", "3.0d"]);
  });
});

describe("JRNL import form", () => {
  it("round-trips the mapping text, quoting columns with spaces", () => {
    const m = { time: "Executed At", symbol: "Ticker", qty: "Shares" };
    expect(textToMapping(mappingToText(m))).toEqual(m);
  });
  it("sends the mapping only for the generic format and the date order only when chosen", () => {
    const f = { text: "x", name: "", broker: "generic", mapping: "time=When symbol=Ticker", dateOrder: "", currency: "eur" };
    expect(importBody(f)).toEqual({ text: "x", name: "pasted", broker: "generic", currency: "EUR", mapping: { time: "When", symbol: "Ticker" } });
    expect(importBody({ ...f, broker: "ibkr", dateOrder: "DMY" })).toEqual({ text: "x", name: "pasted", broker: "ibkr", currency: "EUR", date_order: "DMY" });
  });
  it("cycles a list", () => {
    expect(nextOf(["a", "b"], "b")).toBe("a");
  });
});
