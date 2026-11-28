/**
 * Every ta.* function against hand-worked values (closes 1..10, high = close + 1, low = close - 1, volume 100),
 * and ta.sma / ema / rsi / atr / macd / bb against the chart's indicator catalog (`lib.*`) after warm-up.
 */
import { describe, expect, it } from "vitest";
import { barsFromCloses, expectClose, plot, runScript, walk } from "./testkit";
import { TA_NAMES } from "./ta";
import { BUILTINS } from "./names";

const NaNs = (n: number) => new Array(n).fill(NaN);
const closes = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
const bars = barsFromCloses(closes);

/** Run `plot(<expr>, "x")` over the 10 closes. */
const ta = (expr: string, b = bars) => plot(runScript(`indicator("t")\nplot(${expr}, "x")\n`, b), "x");

describe("ta.* hand values", () => {
  it("sma", () => expectClose(ta("ta.sma(close, 3)"), [...NaNs(2), 2, 3, 4, 5, 6, 7, 8, 9]));
  it("ema (seed = sma of the first n)", () => expectClose(ta("ta.ema(close, 3)"), [...NaNs(2), 2, 3, 4, 5, 6, 7, 8, 9]));
  it("rma", () => {
    const e = [...NaNs(2), 2];
    e.push(2 + (4 - 2) / 3);
    e.push(e[3] + (5 - e[3]) / 3);
    expectClose(ta("ta.rma(close, 3)").slice(0, 5), e);
  });
  it("wma weights the newest bar most", () => {
    const v = ta("ta.wma(close, 3)");
    expectClose(v.slice(0, 4), [NaN, NaN, 14 / 6, 20 / 6]);
  });
  it("vwma with flat volume equals sma", () => expectClose(ta("ta.vwma(close, 3)"), ta("ta.sma(close, 3)")));
  it("stdev and variance are population", () => {
    expectClose(ta("ta.variance(close, 3)").slice(2, 4), [2 / 3, 2 / 3]);
    expectClose(ta("ta.stdev(close, 3)").slice(2, 4), [Math.sqrt(2 / 3), Math.sqrt(2 / 3)]);
  });
  it("highest and lowest", () => {
    expectClose(ta("ta.highest(close, 3)"), [...NaNs(2), 3, 4, 5, 6, 7, 8, 9, 10]);
    expectClose(ta("ta.lowest(close, 3)"), [...NaNs(2), 1, 2, 3, 4, 5, 6, 7, 8]);
  });
  it("change, mom, roc", () => {
    expectClose(ta("ta.change(close)"), [NaN, 1, 1, 1, 1, 1, 1, 1, 1, 1]);
    expectClose(ta("ta.change(close, 2)"), [NaN, NaN, 2, 2, 2, 2, 2, 2, 2, 2]);
    expectClose(ta("ta.mom(close, 3)").slice(0, 5), [NaN, NaN, NaN, 3, 3]);
    expectClose(ta("ta.roc(close, 1)").slice(0, 3), [NaN, 100, 50]);
  });
  it("cum skips na", () => {
    expectClose(ta("ta.cum(close)").slice(0, 4), [1, 3, 6, 10]);
    expectClose(ta("ta.cum(close > 5 ? close : na)").slice(0, 8), [0, 0, 0, 0, 0, 6, 13, 21]);
  });
  it("tr and atr (rma of tr)", () => {
    expectClose(ta("ta.tr()"), closes.map(() => 2));
    expectClose(ta("ta.atr(3)"), [...NaNs(2), ...closes.slice(2).map(() => 2)]);
  });
  it("crossover / crossunder / cross", () => {
    expectClose(ta("ta.crossover(close, 5.5)"), [0, 0, 0, 0, 0, 1, 0, 0, 0, 0]);
    expectClose(ta("ta.crossunder(5.5, close)"), [0, 0, 0, 0, 0, 1, 0, 0, 0, 0]);
    expectClose(ta("ta.cross(close, 5.5)"), [0, 0, 0, 0, 0, 1, 0, 0, 0, 0]);
    expectClose(ta("ta.crossunder(close, 5.5)"), closes.map(() => 0));
  });
  it("a crossover with na is false", () => expectClose(ta("ta.crossover(close, na)"), closes.map(() => 0)));
  it("rising and falling", () => {
    expectClose(ta("ta.rising(close, 2)"), [0, 0, 1, 1, 1, 1, 1, 1, 1, 1]);
    expectClose(ta("ta.falling(close, 2)"), closes.map(() => 0));
  });
  it("barssince", () => expectClose(ta("ta.barssince(close == 4)").slice(0, 6), [NaN, NaN, NaN, 0, 1, 2]));
  it("valuewhen (0 = newest)", () => {
    expectClose(ta("ta.valuewhen(close % 2 == 0, close, 0)").slice(0, 6), [NaN, 2, 2, 4, 4, 6]);
    expectClose(ta("ta.valuewhen(close % 2 == 0, close, 1)").slice(0, 6), [NaN, NaN, NaN, 2, 2, 4]);
  });
  it("linreg", () => {
    expectClose(ta("ta.linreg(close, 3, 0)"), [...NaNs(2), 3, 4, 5, 6, 7, 8, 9, 10]);
    expectClose(ta("ta.linreg(close, 3, 1)"), [...NaNs(2), 2, 3, 4, 5, 6, 7, 8, 9]);
  });
  it("rsi: all gains is 100, all losses is 0", () => {
    expectClose(ta("ta.rsi(close, 3)").slice(3), [100, 100, 100, 100, 100, 100, 100]);
    expectClose(ta("ta.rsi(close, 3)", barsFromCloses([...closes].reverse())).slice(3), [0, 0, 0, 0, 0, 0, 0]);
  });
  it("rsi hand value", () => {
    // changes: +1 +1 -1 : up = 2/3, down = 1/3 -> rsi = 100 - 100/(1+2) = 66.667
    const v = ta("ta.rsi(close, 3)", barsFromCloses([1, 2, 3, 2]));
    expectClose(v, [NaN, NaN, NaN, 100 - 100 / 3]);
  });
  it("macd tuple", () => {
    const res = runScript(`indicator("t")\n[m, s, h] = ta.macd(close, 2, 3, 2)\nplot(m, "m")\nplot(s, "s")\nplot(h, "h")\n`, bars);
    const m = plot(res, "m");
    // ema2 and ema3 of a straight line 1..10: ema2 = close - 0.5 (from idx1... seeded), ema3 = close - 1
    expect(m[2]).toBeCloseTo(0.5, 9);
    expect(plot(res, "h")[5]).toBeCloseTo(plot(res, "m")[5] - plot(res, "s")[5], 12);
  });
  it("bb tuple", () => {
    const res = runScript(`indicator("t")\n[mid, up, lo] = ta.bb(close, 3, 2)\nplot(mid, "mid")\nplot(up, "up")\nplot(lo, "lo")\n`, bars);
    expect(plot(res, "mid")[2]).toBe(2);
    expect(plot(res, "up")[2]).toBeCloseTo(2 + 2 * Math.sqrt(2 / 3), 12);
    expect(plot(res, "lo")[2]).toBeCloseTo(2 - 2 * Math.sqrt(2 / 3), 12);
  });
  it("stoch", () => {
    // window of 3 at idx2: highest high = 4, lowest low = 0, close = 3 -> 75
    expectClose(ta("ta.stoch(close, high, low, 3)").slice(0, 4), [NaN, NaN, 75, 100 * (4 - 1) / (5 - 1)]);
  });
  it("na inside a window gives na", () => {
    expectClose(ta("ta.sma(close > 3 ? close : na, 2)").slice(0, 6), [NaN, NaN, NaN, NaN, 4.5, 5.5]);
  });
  it("a length that is not a whole number is an error", () => {
    const res = runScript(`indicator("t")\nplot(ta.sma(close, 2.5), "x")\n`, bars);
    expect(res.error?.msg).toContain("WHOLE NUMBER");
  });
  it("names.ts and ta.ts agree", () => {
    const named = BUILTINS.filter((b) => b.name.startsWith("ta.")).map((b) => b.name.slice(3));
    expect(named.sort()).toEqual([...TA_NAMES].sort());
  });
});

describe("ta.* against the chart catalog (lib.*)", () => {
  const b = walk(400);
  const cmp = (taExpr: string, libExpr: string, warm: number, tol = 1e-6) => {
    const res = runScript(`indicator("t")\nplot(${taExpr}, "a")\nplot(${libExpr}, "b")\n`, b);
    const a = plot(res, "a");
    const c = plot(res, "b");
    for (let i = warm; i < a.length; i++) {
      if (!(Math.abs(a[i] - c[i]) <= tol * Math.max(1, Math.abs(c[i])))) throw new Error(`${taExpr} vs ${libExpr} at ${i}: ${a[i]} vs ${c[i]}`);
    }
  };
  it("sma", () => cmp("ta.sma(close, 20)", "lib.SMA(20)", 19));
  it("ema", () => cmp("ta.ema(close, 20)", "lib.EMA(20)", 19));
  it("rsi", () => cmp("ta.rsi(close, 14)", "lib.RSI(14)", 14));
  it("atr", () => cmp("ta.atr(14)", "lib.ATR(14)", 14));
  it("macd line", () => {
    const res = runScript(`indicator("t")\n[m, s, h] = ta.macd(close, 12, 26, 9)\n[lm, ls, lh] = lib.MACD(12, 26, 9)\nplot(m, "m")\nplot(lm, "lm")\nplot(s, "s")\nplot(ls, "ls")\n`, b);
    const m = plot(res, "m");
    const lm = plot(res, "lm");
    const s = plot(res, "s");
    const ls = plot(res, "ls");
    for (let i = 40; i < m.length; i++) {
      expect(Math.abs(m[i] - lm[i])).toBeLessThan(1e-6);
      expect(Math.abs(s[i] - ls[i])).toBeLessThan(1e-6);
    }
  });
  it("bollinger bands", () => {
    const res = runScript(`indicator("t")\n[a, u, l] = ta.bb(close, 20, 2)\n[la, lu, ll] = lib.BB(20, 2)\nplot(u, "u")\nplot(lu, "lu")\nplot(l, "l")\nplot(ll, "ll")\n`, b);
    const u = plot(res, "u");
    const lu = plot(res, "lu");
    for (let i = 20; i < u.length; i++) expect(Math.abs(u[i] - lu[i])).toBeLessThan(1e-6);
  });
});
