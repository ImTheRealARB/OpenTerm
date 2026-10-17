import { describe, expect, it } from "vitest";
import { parseBarsCsv } from "./csvImport";
import { fmtMetric, METRIC_ROWS } from "./metricsFormat";
import { parseBtArgs, parseRule } from "./ruleParse";
import { fmtP, histogram } from "./validationFormat";

/*
 * Phase 12 pure modules (spec: docs/specs/PHASE_12.md), written before the code.
 * ruleParse and metricsFormat landed in step 4, csvImport in step 8.
 */

describe("ruleParse (step 4): same grammar and columns as backend bt/rules.py", () => {
  it("accepts the rule forms", () => {
    for (const r of ["SMA20>SMA50", "CLOSE>SMA200", "RSI14<30", "EMA12 CROSS> EMA26", "RSI14<30 AND CLOSE>SMA200",
      "RET20>0.05 OR HIGH20<=CLOSE", "sma20 > sma50"]) expect(parseRule(r)).toEqual({ ok: true });
  });

  it("rejects with the 0-based column of the offending character", () => {
    const cases: [string, number][] = [["SMA20>>SMA50", 6], ["FOO>1", 0], ["SMA0>CLOSE", 0], ["SMA20", 5],
      ["SMA20>SMA50 AND", 15], ["RSI14<", 6]];
    for (const [text, col] of cases) {
      const r = parseRule(text);
      expect(r.ok).toBe(false);
      expect(r.col).toBe(col);
      expect(r.error).toMatch(/\S/);
    }
  });

  it("parses BT command arguments", () => {
    expect(parseBtArgs(["AAPL", "SMA20>SMA50", "1D", "5Y"])).toMatchObject({
      ok: true, symbols: ["AAPL"], rule: "SMA20>SMA50", interval: "1D", range: "5Y", short: false,
    });
    expect(parseBtArgs(["SPY,QQQ", "RSI14<30", "1D", "10Y", "SHORT", "FEES=5", "SLIP=5", "CASH=50000", "BENCH=SPY"]))
      .toMatchObject({ ok: true, symbols: ["SPY", "QQQ"], short: true, fees: 5, slip: 5, cash: 50000, bench: "SPY" });
    expect(parseBtArgs(["AAPL", "SMA20>SMA50", "FEES=-1"]).ok).toBe(false);
    expect(parseBtArgs([]).ok).toBe(false);
    // subcommands are not rules
    expect(parseBtArgs(["RUNS"])).toMatchObject({ ok: true, sub: "RUNS" });
  });
});

describe("metricsFormat (step 4)", () => {
  it("formats each metric kind", () => {
    expect(fmtMetric("total_return", 0.12345)).toBe("+12.35%");
    expect(fmtMetric("max_drawdown", -0.2075)).toBe("-20.75%");
    expect(fmtMetric("sharpe", 0.81119)).toBe("0.81");
    expect(fmtMetric("trade_count", 29)).toBe("29");
    expect(fmtMetric("final_value", 422839.137)).toBe("422,839.14");
    expect(fmtMetric("profit_factor", null)).toBe("—");
  });

  it("lists the metric rows in the spec's order", () => {
    expect(METRIC_ROWS.map((r: { key: string }) => r.key).slice(0, 5))
      .toEqual(["final_value", "total_return", "annual_return", "max_drawdown", "sharpe"]);
  });
});

describe("csvImport (step 8)", () => {
  it("parses bars, sorts them and reports bad rows by number", () => {
    const ok = parseBarsCsv("Date,Open,High,Low,Close,Volume\n2024-01-03,2,3,1,2.5,10\n2024-01-02,1,2,0.5,1.5,5\n");
    expect(ok.errors).toEqual([]);
    expect(ok.bars.map((b: { t: string }) => b.t)).toEqual(["2024-01-02", "2024-01-03"]);
    expect(ok.bars[0]).toEqual({ t: "2024-01-02", o: 1, h: 2, l: 0.5, c: 1.5, v: 5 });
    expect(parseBarsCsv("date,close\n2024-01-02,1\n").errors[0]).toMatch(/NEEDS/);
    expect(parseBarsCsv("date,open,high,low,close\n2024-13-02,1,1,1,1\n").errors[0]).toMatch(/ROW 1/);
    expect(parseBarsCsv("date,open,high,low,close\n2024-01-02,1,1,1,abc\n").errors[0]).toMatch(/ROW 1/);
    // volume is optional
    expect(parseBarsCsv("date,open,high,low,close\n2024-01-02,1,1,1,1\n").bars[0].v).toBeUndefined();
  });
});

describe("BT MC / WF (step 6)", () => {
  it("BT MC|WF <run args> is a run that validates itself", () => {
    expect(parseBtArgs(["MC", "AAPL", "SMA20>SMA50", "1D", "10Y"])).toMatchObject({
      ok: true, symbols: ["AAPL"], rule: "SMA20>SMA50", range: "10Y", val: "MC",
    });
    expect(parseBtArgs(["wf", "SPY", "RSI14<30"])).toMatchObject({ ok: true, val: "WF" });
    expect(parseBtArgs(["AAPL", "SMA20>SMA50"]).ok && "val" in parseBtArgs(["AAPL", "SMA20>SMA50"])).toBe(false);
  });

  it("BT MC with nothing to run, or with another subcommand, is an error", () => {
    expect(parseBtArgs(["MC"]).ok).toBe(false);
    expect(parseBtArgs(["MC", "RUNS"]).ok).toBe(false);
    const bad = parseBtArgs(["MC", "AAPL", "SMA20>>SMA50"]);
    expect(bad).toMatchObject({ ok: false, col: 6, rule: "SMA20>>SMA50" });
  });

  it("histogram: counts, scaled bars, the actual value's bin", () => {
    const h = histogram([1, 1, 1, 2, 3, 4, 4], 3, 4, 10);
    expect(h.map((r) => r.count)).toEqual([3, 1, 3]);
    expect(h.map((r) => r.bar)).toEqual([10, 3, 10]);
    expect(h.map((r) => r.actual)).toEqual([false, false, true]);
    expect(h[0].lo).toBe(1);
    expect(h[2].hi).toBe(4);
  });

  it("histogram: the range widens to include the actual value, a constant sample still has width, nothing draws nothing", () => {
    const wide = histogram([0, 1], 4, 5);
    expect(wide[wide.length - 1].hi).toBe(5);
    expect(wide.reduce((n, r) => n + r.count, 0)).toBe(2);
    expect(wide.filter((r) => r.actual)).toHaveLength(1);
    const flat = histogram([2, 2, 2], 2, null);
    expect(flat.reduce((n, r) => n + r.count, 0)).toBe(3);
    expect(flat[0].hi).toBeGreaterThan(flat[0].lo);
    expect(histogram([], 5, 1)).toEqual([]);
    expect(histogram([NaN, Infinity], 5, 1)).toEqual([]);
  });

  it("p-values read as shares", () => {
    expect(fmtP(0.041)).toBe("4.1%");
    expect(fmtP(null)).toBe("—");
    expect(fmtP(NaN)).toBe("—");
  });
});

describe("BT OPEN / EXPORT (step 7)", () => {
  it("are subcommands with their arguments", () => {
    expect(parseBtArgs(["OPEN", "abc123"])).toMatchObject({ ok: true, sub: "OPEN", args: ["abc123"] });
    expect(parseBtArgs(["export", "abc123", "pine"])).toMatchObject({ ok: true, sub: "EXPORT", args: ["abc123", "pine"] });
    expect(parseBtArgs(["RUNS"])).toMatchObject({ ok: true, sub: "RUNS", args: [] });
  });
});

describe("csvImport extra rules (step 8)", () => {
  it("rejects the same files the backend rejects", () => {
    const head = "date,open,high,low,close\n2024-01-02,1,1,1,1\n";
    expect(parseBarsCsv(head + "2024-01-02,1,1,1,1\n").errors[0]).toMatch(/ROW 2: DUPLICATE DATE/);
    expect(parseBarsCsv(head + "2024-01-03,0,1,1,1\n").errors[0]).toMatch(/ROW 2: PRICES MUST BE POSITIVE/);
    expect(parseBarsCsv(head + "2024-01-03,1,1,2,1\n").errors[0]).toMatch(/ROW 2: HIGH BELOW LOW/);
    expect(parseBarsCsv(head + "2024-01-03,1,1,1,NaN\n").errors[0]).toMatch(/ROW 2: BAD NUMBER IN close/);
    expect(parseBarsCsv(head + "2024-02-30,1,1,1,1\n").errors[0]).toMatch(/ROW 2: BAD DATE/);
    expect(parseBarsCsv(head + "2024-01-03,1,1,1\n").errors[0]).toMatch(/ROW 2: HAS 4 COLUMNS/);
    expect(parseBarsCsv(head).errors).toEqual(["NEEDS AT LEAST 2 ROWS"]);
    expect(parseBarsCsv("").errors).toEqual(["EMPTY FILE"]);
  });

  it("reads any column order, a BOM, CRLF and a time after the date", () => {
    const got = parseBarsCsv("\uFEFFClose,DATE,low,High,open,Volume\r\n3,2024-01-03 00:00:00,1,4,2,\r\n2,2024-01-02T09:30,0.5,3,1,7\r\n");
    expect(got.errors).toEqual([]);
    expect(got.bars).toEqual([
      { t: "2024-01-02", o: 1, h: 3, l: 0.5, c: 2, v: 7 },
      { t: "2024-01-03", o: 2, h: 4, l: 1, c: 3 },
    ]);
    expect(got.hasVolume).toBe(true);
  });

  it("collects at most 20 problems", () => {
    const rows = Array.from({ length: 50 }, () => "x,1,1,1,1").join("\n");
    expect(parseBarsCsv("date,open,high,low,close\n" + rows).errors).toHaveLength(20);
  });
});

describe("BT strategies (step 4B)", () => {
  it("@name in the rule position names a saved strategy", () => {
    expect(parseBtArgs(["AAPL", "@MySma", "1D", "5Y"])).toMatchObject({ ok: true, symbols: ["AAPL"], strategy: "mysma", rule: "@MySma", range: "5Y" });
    expect(parseBtArgs(["MC", "AAPL", "@golden"])).toMatchObject({ ok: true, strategy: "golden", val: "MC" });
    expect(parseBtArgs(["AAPL", "@bad name!"]).ok).toBe(false);
    expect(parseBtArgs(["AAPL", "@"]).ok).toBe(false);
  });

  it("EDIT, LOAD, SAVE and DEL are subcommands", () => {
    for (const s of ["EDIT", "LOAD", "SAVE", "DEL"]) expect(parseBtArgs([s, "x"])).toMatchObject({ ok: true, sub: s, args: ["x"] });
  });
});
