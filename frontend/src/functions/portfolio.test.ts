import { describe, expect, it } from "vitest";
import { exportPositions, importPositions, parseAmount, parseCsv, serializeCsv } from "./portfolioCsv";
import { calcRow, fxSymbol, totals, weight, type PosInput } from "./portfolioMath";

describe("parseCsv / serializeCsv", () => {
  it("handles quotes, commas in fields, BOM and CRLF", () => {
    const text = '﻿symbol,notes\r\nAAPL,"long, core"\r\nMSFT,"say ""hi"""\r\n';
    expect(parseCsv(text)).toEqual([["symbol", "notes"], ["AAPL", "long, core"], ["MSFT", 'say "hi"']]);
  });

  it("keeps newlines inside quoted fields and reads LF / CR endings", () => {
    expect(parseCsv('a,"x\ny"\nb,2')).toEqual([["a", "x\ny"], ["b", "2"]]);
    expect(parseCsv("a,1\rb,2\r")).toEqual([["a", "1"], ["b", "2"]]);
    expect(parseCsv("a,,c\n")).toEqual([["a", "", "c"]]);
  });

  it("sniffs semicolon and tab delimiters", () => {
    expect(parseCsv("symbol;qty\nAAPL;1,5")).toEqual([["symbol", "qty"], ["AAPL", "1,5"]]);
    expect(parseCsv("symbol\tqty\nAAPL\t2")).toEqual([["symbol", "qty"], ["AAPL", "2"]]);
  });

  it("round-trips through serialize", () => {
    const rows = [["a", "b,c", 'd"e', "f\r\ng", " pad "], ["1", "", "x", "y", "z"]];
    const text = serializeCsv(rows);
    expect(text.endsWith("\r\n")).toBe(true);
    expect(parseCsv(text)).toEqual(rows);
  });

  it("parses amounts tolerantly but never guesses", () => {
    expect(parseAmount("1,234.50")).toBe(1234.5);
    expect(parseAmount("$12")).toBe(12);
    expect(parseAmount("(10)")).toBe(-10);
    expect(parseAmount("1 000")).toBe(1000);
    expect(parseAmount("")).toBeNull();
    expect(parseAmount("12abc")).toBeNaN();
  });
});

describe("importPositions", () => {
  it("maps tolerant headers and reports every bad row with its line", () => {
    const text = [
      "Ticker,Shares,Avg Cost,Currency,Comment",
      "aapl,10,150.25,USD,core",
      "MSFT,5,,,",
      ",3,1,,",
      "NVDA,zero,1,,",
      "TSLA,0,1,,",
      "VOD.L,1000,72.5,GBp,\"pence, LSE\"",
      "",
      "BAD SYM,1,1,,",
      "AAPL,10,200,USD,",
      "IBM,1,-5,,",
      "SAP,1,100,EURO,",
    ].join("\r\n");
    const r = importPositions(text);
    expect(r.mapping).toEqual({ symbol: "Ticker", qty: "Shares", cost: "Avg Cost", currency: "Currency", notes: "Comment" });
    expect(r.rows.map((x) => [x.line, x.symbol, x.qty, x.cost, x.currency, x.notes])).toEqual([
      [2, "AAPL", 10, 150.25, "USD", "core"],
      [3, "MSFT", 5, null, null, null],
      [7, "VOD.L", 1000, 72.5, "GBp", "pence, LSE"],
      [10, "AAPL", 10, 200, "USD", null],
    ]);
    expect(r.errors.map((e) => [e.line, e.reason])).toEqual([
      [4, "NO SYMBOL"],
      [5, "BAD QUANTITY: zero"],
      [6, "QUANTITY IS 0"],
      [9, "BAD SYMBOL: BAD SYM"],
      [11, "BAD COST: -5"],
      [12, "BAD CURRENCY: EURO"],
    ]);
    expect(r.warnings).toEqual(["AAPL ON LINES 2, 10: COMBINED AS LOTS (AVERAGE COST)"]);
    // Every non-blank data row is accounted for.
    expect(r.rows.length + r.errors.length).toBe(10);
  });

  it("other header spellings: qty / price, cost basis totals", () => {
    expect(importPositions("Symbol,Qty,Price\nAAPL,2,10").rows[0]).toMatchObject({ symbol: "AAPL", qty: 2, cost: 10 });
    expect(importPositions("symbol,quantity,cost\nAAPL,2,10").rows[0]).toMatchObject({ qty: 2, cost: 10 });
    const basis = importPositions("Symbol,Quantity,Cost Basis\nAAPL,4,\"1,000\"");
    expect(basis.rows[0]).toMatchObject({ qty: 4, cost: 250 });
    expect(basis.warnings[0]).toBe("AVG COST = Cost Basis / QUANTITY");
  });

  it("reads a headerless file and says so; an unknown header fails loudly", () => {
    const r = importPositions("AAPL,10,150\nMSFT,5");
    expect(r.rows.map((x) => x.symbol)).toEqual(["AAPL", "MSFT"]);
    expect(r.warnings[0]).toMatch(/NO HEADER ROW/);
    const bad = importPositions("Name,Value\nApple,10\nMicrosoft,5");
    expect(bad.rows).toEqual([]);
    expect(bad.errors.map((e) => e.line)).toEqual([1, 2, 3]);
    expect(importPositions("").warnings).toEqual(["NO ROWS FOUND"]);
  });

  it("exports a CSV that imports back to the same positions", () => {
    const positions = [
      { symbol: "AAPL", qty: 10, cost: 150.25, currency: "USD", notes: "core, long" },
      { symbol: "MSFT", qty: -5, cost: null, currency: null, notes: null },
    ];
    const text = exportPositions(positions, (s) => (s === "AAPL" ? 200 : null));
    expect(text.split("\r\n")[0]).toBe("symbol,quantity,avg_cost,currency,notes,last,market_value,unrealized_pnl");
    expect(text.split("\r\n")[1]).toBe('AAPL,10,150.25,USD,"core, long",200,2000,497.5');
    const back = importPositions(text);
    expect(back.errors).toEqual([]);
    expect(back.rows.map(({ symbol, qty, cost, currency, notes }) => ({ symbol, qty, cost, currency, notes }))).toEqual(positions);
  });
});

describe("portfolio math", () => {
  const pos = (o: Partial<PosInput>): PosInput => ({
    symbol: "AAPL", qty: 10, cost: 100, posCurrency: null, quoteCurrency: "USD", last: 110, change: 2, ...o,
  });
  const noFx = () => null;

  it("values a row: day P&L, market value, unrealized P&L and %", () => {
    const c = calcRow(pos({}), "USD", noFx);
    expect(c).toMatchObject({ mv: 1100, day: 20, unrl: 100, unrlPct: 10, mvBase: 1100, converted: false });
    const short = calcRow(pos({ qty: -10 }), "USD", noFx);
    expect(short.unrl).toBe(-100);
    expect(short.unrlPct).toBe(-10);
    expect(calcRow(pos({ cost: null }), "USD", noFx).unrl).toBeNull();
    expect(calcRow(pos({ last: null }), "USD", noFx).mv).toBeNull();
  });

  it("converts other currencies with live FX, minor units included", () => {
    expect(fxSymbol("EUR", "USD")).toBe("EURUSD=X");
    expect(fxSymbol("GBp", "USD")).toBe("GBPUSD=X");
    expect(fxSymbol("USD", "USD")).toBeNull();
    const rate = (fx: string) => ({ "EURUSD=X": 1.1, "GBPUSD=X": 1.25 })[fx] ?? null;
    const eur = calcRow(pos({ quoteCurrency: "EUR", last: 50, change: 1 }), "USD", rate);
    expect(eur.mvBase).toBeCloseTo(550);
    expect(eur.converted).toBe(true);
    const vod = calcRow(pos({ symbol: "VOD.L", qty: 1000, cost: 70, quoteCurrency: "GBp", last: 72, change: 0.5 }), "USD", rate);
    expect(vod.mv).toBe(72000); // pence
    expect(vod.mvBase).toBeCloseTo(900); // 720 GBP * 1.25
  });

  it("never mixes currencies silently", () => {
    const rows = [
      { symbol: "AAPL", calc: calcRow(pos({}), "USD", noFx) },
      { symbol: "SAP.DE", calc: calcRow(pos({ symbol: "SAP.DE", quoteCurrency: "EUR", last: 200 }), "USD", noFx) },
      { symbol: "X", calc: calcRow(pos({ posCurrency: "EUR" }), "USD", noFx) },
      { symbol: "NOPX", calc: calcRow(pos({ last: null }), "USD", noFx) },
    ];
    const t = totals(rows, "USD");
    expect(t.mv).toBe(1100);
    expect(t.unconverted).toEqual([
      { ccy: "EUR", mv: 2000, day: 20, unrl: 1000, count: 1 },
      { ccy: "USD (CCY MISMATCH)", mv: 1100, day: 20, unrl: 100, count: 1 },
    ]);
    expect(t.noPrice).toEqual(["NOPX"]);
    expect(t.converted).toEqual([]);
  });

  it("totals, day %, unrealized % and weights", () => {
    const rate = (fx: string) => (fx === "EURUSD=X" ? 2 : null);
    const a = calcRow(pos({}), "USD", rate); // mv 1100, day 20, unrl 100, cost 1000
    const b = calcRow(pos({ quoteCurrency: "EUR", qty: 5, cost: 80, last: 90, change: -1 }), "USD", rate); // mvBase 900
    const t = totals([{ symbol: "A", calc: a }, { symbol: "B", calc: b }], "USD");
    expect(t.mv).toBeCloseTo(2000);
    expect(t.day).toBeCloseTo(20 - 10);
    expect(t.dayPct).toBeCloseTo((10 / (2000 - 10)) * 100);
    expect(t.unrl).toBeCloseTo(100 + 100);
    expect(t.cost).toBeCloseTo(1000 + 800);
    expect(t.unrlPct).toBeCloseTo((200 / 1800) * 100);
    expect(t.converted).toEqual(["EUR"]);
    expect(weight(a, t)).toBeCloseTo(55);
    expect(weight(b, t)).toBeCloseTo(45);
  });
});

describe("CSV formula injection (audit D-3)", () => {
  it("neutralizes text cells that start like a formula, and the export reads back unchanged", () => {
    const text = exportPositions([
      { symbol: "AAPL", qty: 1, cost: 10, currency: "USD", notes: "=HYPERLINK(\"http://x\")" },
      { symbol: "MSFT", qty: 2, cost: 5, currency: null, notes: "-SUM(A1)" },
      { symbol: "GOOG", qty: 3, cost: 4, currency: null, notes: "plain note" },
    ]);
    expect(text).toContain("'=HYPERLINK");
    expect(text).toContain("'-SUM(A1)");
    expect(text).not.toMatch(/,=HYPERLINK/);
    const back = importPositions(text);
    expect(back.rows.map((r) => r.notes)).toEqual(['=HYPERLINK("http://x")', "-SUM(A1)", "plain note"]);
  });

  it("leaves negative numbers alone", () => {
    expect(serializeCsv([["a", "-12.5", "+3"]])).toBe("a,-12.5,+3\r\n");
  });
});
