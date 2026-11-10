import { describe, expect, it } from "vitest";
import { confirmReady, confirmWord, EMPTY_DRAFT, mandateText, parseMandate, parseOrdArgs, toBody, type Draft } from "./ordModel";
import type { Mandate } from "../net/ordersApi";

const M: Mandate = { symbols: ["AAPL"], max_shares: 100, max_notional: 5000, max_gross: 25000, max_trades_per_day: 10 };

describe("ORD command words", () => {
  it("is paper by default", () => {
    const d = parseOrdArgs([]) as Draft;
    expect(d.broker).toBe("alpaca-paper");
    expect(parseOrdArgs(["AAPL", "BUY", "10"])).toMatchObject({ broker: "alpaca-paper", symbol: "AAPL", side: "buy", qty: "10", type: "market" });
  });

  it("reads broker, side, quantity, symbol, limit price and time in force in any order", () => {
    expect(parseOrdArgs(["alpaca", "sell", "5", "msft", "lmt", "421.5", "gtc"])).toMatchObject({ broker: "alpaca-live", side: "sell", qty: "5", symbol: "MSFT", type: "limit", price: "421.5", tif: "gtc" });
    expect(parseOrdArgs(["KITE", "RELIANCE.NS", "STP", "2900"])).toMatchObject({ broker: "kite", symbol: "RELIANCE.NS", type: "stop", price: "2900" });
  });

  it("rejects what it cannot read", () => {
    expect(parseOrdArgs(["AAPL", "LMT"])).toEqual({ error: "LMT NEEDS A PRICE" });
    expect(parseOrdArgs(["AAPL", "MSFT"])).toMatchObject({ error: expect.stringContaining("NOT AN ORDER WORD") });
  });
});

describe("ORD ticket", () => {
  const ok: Draft = { ...EMPTY_DRAFT, symbol: "aapl", qty: "10" };

  it("builds a body with no mode field at all", () => {
    const b = toBody(ok);
    expect(b).toEqual({ broker: "alpaca-paper", symbol: "AAPL", side: "buy", qty: 10, type: "market", tif: "day" });
    expect(Object.keys(b as object)).not.toContain("mode");
    expect(toBody({ ...ok, type: "limit", price: "190.5" })).toMatchObject({ type: "limit", limit_price: 190.5 });
    expect(toBody({ ...ok, type: "stop", price: "180" })).toMatchObject({ type: "stop", stop_price: 180 });
  });

  it("says what is missing", () => {
    expect(toBody({ ...ok, symbol: "" })).toEqual({ error: "ENTER A SYMBOL" });
    expect(toBody({ ...ok, qty: "0" })).toMatchObject({ error: expect.stringContaining("QTY") });
    expect(toBody({ ...ok, qty: "" })).toMatchObject({ error: expect.stringContaining("QTY") });
    expect(toBody({ ...ok, type: "limit" })).toMatchObject({ error: expect.stringContaining("NEEDS A PRICE") });
  });

  it("makes a live order a typed confirm and a paper order a single key", () => {
    expect(confirmWord("paper", "AAPL")).toBeNull();
    expect(confirmReady("paper", "AAPL", "")).toBe(true);
    expect(confirmWord("live", "aapl")).toBe("AAPL");
    expect(confirmReady("live", "AAPL", "")).toBe(false);
    expect(confirmReady("live", "AAPL", " aapl ")).toBe(true);
    expect(confirmReady("live", "AAPL", "MSFT")).toBe(false);
  });
});

describe("ORD mandate text", () => {
  it("round-trips", () => {
    expect(mandateText(M)).toBe("AAPL SHARES=100 NOTIONAL=5000 GROSS=25000 TRADES=10");
    expect(parseMandate(mandateText(M), M)).toEqual(M);
  });

  it("edits symbols and one limit", () => {
    expect(parseMandate("aapl,msft shares=50 trades=3.9", M)).toEqual({ ...M, symbols: ["AAPL", "MSFT"], max_shares: 50, max_trades_per_day: 3 });
  });

  it("refuses bad words and negative numbers", () => {
    expect(parseMandate("SHARES=-1", M)).toMatchObject({ error: expect.any(String) });
    expect(parseMandate("COLOUR=1", M)).toMatchObject({ error: expect.any(String) });
    expect(parseMandate("A B=", M)).toMatchObject({ error: expect.any(String) });
  });
});
