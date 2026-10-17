import { describe, expect, it } from "vitest";
import { alertMet, describeRule, parseAlrt, parseRule, tickPct } from "./alertArgs";
import { parseNumber, parsePort } from "./portfolioArgs";

const sec = (symbol: string) => ({ symbol });

describe("parsePort", () => {
  it("views, deletes, exports, imports", () => {
    expect(parsePort([])).toEqual({ kind: "view" });
    expect(parsePort(["core"])).toEqual({ kind: "view", name: "CORE" });
    expect(parsePort(["DEL", "core"])).toEqual({ kind: "delete", name: "CORE" });
    expect(parsePort(["del"]).kind).toBe("error");
    expect(parsePort(["core", "export"])).toEqual({ kind: "export", name: "CORE" });
    expect(parsePort(["core", "IMPORT"])).toEqual({ kind: "import", name: "CORE" });
    expect(parsePort(["core", "IMPORT", "x"]).kind).toBe("error");
    expect(parsePort(["my/port"])).toEqual({ kind: "error", message: "PORTFOLIO NAME: 1-32 OF A-Z 0-9 _ . -" });
    expect(parsePort(["core", "base", "eur"])).toEqual({ kind: "base", name: "CORE", base: "EUR" });
    expect(parsePort(["core", "base", "euro"]).kind).toBe("error");
  });

  it("adds a lot with optional cost and currency", () => {
    expect(parsePort(["core", "add", "aapl", "10", "150"])).toEqual({ kind: "add", name: "CORE", symbol: "AAPL", qty: 10, cost: 150 });
    expect(parsePort(["core", "ADD", "msft", "5"])).toEqual({ kind: "add", name: "CORE", symbol: "MSFT", qty: 5, cost: null });
    expect(parsePort(["core", "add", "vod.l", "1,000", "@72.5", "GBp"])).toEqual({
      kind: "add", name: "CORE", symbol: "VOD.L", qty: 1000, cost: 72.5, currency: "GBp",
    });
    expect(parsePort(["core", "add", "aapl", "-5", "180"])).toMatchObject({ qty: -5, cost: 180 });
    expect(parsePort(["core", "add", "7203.T", "100", "2500", "jpy"])).toMatchObject({ symbol: "7203.T", currency: "JPY" });
  });

  it("uses the typed security, never the sticky one", () => {
    expect(parsePort(["core", "add", "10", "150"], sec("AAPL"))).toMatchObject({ symbol: "AAPL", qty: 10, cost: 150 });
    expect(parsePort(["core", "add", "msft", "1"], sec("AAPL"))).toMatchObject({ symbol: "MSFT", qty: 1 });
    expect(parsePort(["core", "add", "10"]).kind).toBe("error"); // "10" is the symbol, then no quantity
  });

  it("rejects bad adds and removes", () => {
    expect(parsePort(["core", "add"]).kind).toBe("error");
    expect(parsePort(["core", "add", "aapl"]).kind).toBe("error");
    expect(parsePort(["core", "add", "aapl", "0"])).toEqual({ kind: "error", message: "BAD QUANTITY: 0" });
    expect(parsePort(["core", "add", "aapl", "ten"])).toEqual({ kind: "error", message: "BAD QUANTITY: ten" });
    expect(parsePort(["core", "add", "aapl", "1", "-3"])).toEqual({ kind: "error", message: "BAD COST: -3" });
    expect(parsePort(["core", "add", "aapl", "1", "2", "3"])).toEqual({ kind: "error", message: "BAD COST: 3" });
    expect(parsePort(["core", "rm", "aapl", "msft"])).toEqual({ kind: "remove", name: "CORE", symbols: ["AAPL", "MSFT"] });
    expect(parsePort(["core", "rm"]).kind).toBe("error");
    expect(parsePort(["core", "sell"]).kind).toBe("error");
  });

  it("parses numbers strictly", () => {
    expect(parseNumber("1,234.5")).toBe(1234.5);
    expect(parseNumber("$10")).toBe(10);
    expect(parseNumber("2e3")).toBe(2000);
    expect(parseNumber("1,23")).toBeNull();
    expect(parseNumber("abc")).toBeNull();
  });
});

describe("parseAlrt", () => {
  it("lists, deletes, rearms, clears", () => {
    expect(parseAlrt([])).toEqual({ kind: "list" });
    expect(parseAlrt(["DEL", "3"])).toEqual({ kind: "delete", id: 3 });
    expect(parseAlrt(["del", "x"]).kind).toBe("error");
    expect(parseAlrt(["REARM", "7"])).toEqual({ kind: "rearm", id: 7 });
    expect(parseAlrt(["clear"])).toEqual({ kind: "clear" });
  });

  it("price levels", () => {
    expect(parseAlrt(["aapl", ">", "200"])).toEqual({ kind: "create", symbol: "AAPL", rule: { op: ">", unit: "price", value: 200 } });
    expect(parseAlrt(["AAPL", "<", "180.5"])).toEqual({ kind: "create", symbol: "AAPL", rule: { op: "<", unit: "price", value: 180.5 } });
    expect(parseAlrt(["AAPL>200"])).toMatchObject({ symbol: "AAPL", rule: { op: ">", value: 200 } });
    expect(parseAlrt(["BTC-USD", ">=", "100000"])).toMatchObject({ symbol: "BTC-USD", rule: { op: ">", value: 100000 } });
    expect(parseAlrt([">", "200"], sec("AAPL"))).toMatchObject({ symbol: "AAPL", rule: { op: ">", value: 200 } });
  });

  it("percent vs previous close", () => {
    expect(parseAlrt(["AAPL", "+5%"])).toMatchObject({ rule: { op: ">", unit: "pct", value: 5 } });
    expect(parseAlrt(["AAPL", "-3%"])).toMatchObject({ rule: { op: "<", unit: "pct", value: -3 } });
    expect(parseAlrt(["AAPL", ">", "-2%"])).toMatchObject({ rule: { op: ">", unit: "pct", value: -2 } });
    expect(parseAlrt(["-3%"], sec("^GSPC"))).toMatchObject({ symbol: "^GSPC", rule: { op: "<", value: -3 } });
  });

  it("rejects ambiguous or bad conditions", () => {
    expect(parseAlrt(["AAPL", "5%"])).toEqual({ kind: "error", message: "SAY +5% (UP) OR -5% (DOWN)" });
    expect(parseAlrt(["AAPL", "200"]).kind).toBe("error");
    expect(parseAlrt(["AAPL"]).kind).toBe("error");
    expect(parseAlrt(["AAPL", ">", "-5"]).kind).toBe("error");
    expect(parseAlrt(["AAPL", ">", "abc"]).kind).toBe("error");
    expect(parseAlrt(["AAPL", "+0%"]).kind).toBe("error");
    expect(parseRule("+2000%")).toBe("PERCENT MUST BE AT MOST 1000");
  });
});

describe("alert conditions", () => {
  it("price levels are inclusive", () => {
    const up = { op: ">" as const, unit: "price" as const, value: 200 };
    expect(alertMet(up, 199.99, null, null)).toBe(false);
    expect(alertMet(up, 200, null, null)).toBe(true);
    expect(alertMet({ ...up, op: "<", value: 180 }, 180.01, null, null)).toBe(false);
    expect(alertMet({ ...up, op: "<", value: 180 }, 179, null, null)).toBe(true);
    expect(alertMet(up, NaN, null, null)).toBe(false);
  });

  it("percent uses the tick's pct, else derives it from the change", () => {
    const up5 = { op: ">" as const, unit: "pct" as const, value: 5 };
    expect(alertMet(up5, 105, 5.2, null)).toBe(true);
    expect(alertMet(up5, 105, 4.9, null)).toBe(false);
    expect(alertMet(up5, 105, null, 5)).toBe(true); // prev 100 -> +5%
    expect(alertMet(up5, 105, null, null)).toBe(false); // unknown: never fires
    const dn3 = { op: "<" as const, unit: "pct" as const, value: -3 };
    expect(alertMet(dn3, 97, -3, null)).toBe(true);
    expect(alertMet(dn3, 98, -2, null)).toBe(false);
    expect(tickPct(110, null, 10)).toBeCloseTo(10);
  });

  it("describes rules", () => {
    expect(describeRule({ op: ">", unit: "price", value: 200 })).toBe("> 200");
    expect(describeRule({ op: ">", unit: "pct", value: 5 })).toBe("+5%");
    expect(describeRule({ op: "<", unit: "pct", value: -3 })).toBe("-3%");
    expect(describeRule({ op: ">", unit: "pct", value: -2 })).toBe("> -2%");
  });
});
