import { describe, expect, it } from "vitest";
import { ratesView } from "./ratesArgs";

describe("ratesView", () => {
  it("maps a currency to the curve view, any case", () => {
    expect(ratesView(["eur"])).toEqual({ view: "curve", params: { ccy: "EUR" } });
    expect(ratesView(["JPY"])).toEqual({ view: "curve", params: { ccy: "JPY" } });
  });
  it("maps SPRD and AUCT to their tables", () => {
    expect(ratesView(["sprd"])).toEqual({ view: "spreads", params: {} });
    expect(ratesView(["AUCT"])).toEqual({ view: "auctions", params: {} });
  });
  it("maps NS <ccy> (either order) to the Nelson-Siegel fit of that curve", () => {
    expect(ratesView(["NS", "EUR"])).toEqual({ view: "curve", params: { ccy: "EUR", fit: "NS" } });
    expect(ratesView(["cad", "ns"])).toEqual({ view: "curve", params: { ccy: "CAD", fit: "NS" } });
  });
  it("returns null for anything else instead of guessing", () => {
    expect(ratesView([])).toBeNull();
    expect(ratesView(["USD"])).toBeNull();
    expect(ratesView(["NS"])).toBeNull();
    expect(ratesView(["NS", "USD"])).toBeNull();
    expect(ratesView(["EUR", "GBP"])).toBeNull();
    expect(ratesView(["SPRD", "EUR"])).toBeNull();
  });
});
