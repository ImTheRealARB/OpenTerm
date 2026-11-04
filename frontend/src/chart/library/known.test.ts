/**
 * Known-value checks for the library. Every expected number is worked out from the textbook definition of the indicator
 * (formulas as given in StockCharts ChartSchool / Investopedia) on a series small enough to verify by hand, or follows from
 * a property (constant series, straight ramp). The classic Wilder studies (RSI, ATR, ADX, CCI, MFI) are covered by studies.test.ts.
 */
import { describe, expect, it } from "vitest";
import { runIndicator } from "./catalog";
import type { Cols } from "./types";

const F = (a: number[]) => Float64Array.from(a);
const ramp = (n: number, step = 1, start = 0) => F(Array.from({ length: n }, (_, i) => start + i * step));
const cst = (n: number, x: number) => new Float64Array(n).fill(x);
const ohlcv = (c: Float64Array, spread = 1, vol = 100): Cols => ({
  o: c.slice(),
  h: c.map((x) => x + spread),
  l: c.map((x) => x - spread),
  c,
  v: cst(c.length, vol),
});
const run = (id: string, cols: Cols, p?: number[]) => runIndicator(id, cols, p)!;
const last = (a: Float64Array) => a[a.length - 1];
const near = (x: number, y: number, d = 9) => expect(x).toBeCloseTo(y, d);

describe("moving averages", () => {
  it("WMA weights 1..n", () => near(run("WMA", ohlcv(F([1, 2, 3, 4, 5])), [3])[0][2], 14 / 6));
  it("HMA on a ramp lags by 2/3 for n=16", () => near(last(run("HMA", ohlcv(ramp(100)), [16])[0]), 99 - 2 / 3, 6));
  it("DEMA / TEMA of a constant is the constant, DEMA of a ramp has no lag", () => {
    near(last(run("DEMA", ohlcv(cst(60, 7)), [5])[0]), 7);
    near(last(run("TEMA", ohlcv(cst(60, 7)), [5])[0]), 7);
    near(last(run("DEMA", ohlcv(ramp(300)), [3])[0]), 299, 6);
    near(last(run("TEMA", ohlcv(ramp(300)), [3])[0]), 299, 6);
  });
  it("TRIMA n=5 is SMA(3) of SMA(3)", () => near(run("TRIMA", ohlcv(ramp(20)), [5])[0][10], 8));
  it("KAMA first step with efficiency ratio 1", () => near(run("KAMA", ohlcv(ramp(10)), [2, 2, 30])[0][2], 1 + (4 / 9) * 1));
  it("ZLEMA on a ramp follows price", () => near(last(run("ZLEMA", ohlcv(ramp(300)), [5])[0]), 299, 6));
  it("VWMA", () => near(run("VWMA", { ...ohlcv(F([1, 2, 3])), v: F([1, 1, 2]) }, [3])[0][2], 2.25));
  it("ALMA with centred offset on a ramp sits (n-1)/2 bars back; T3 and McGinley keep constants", () => {
    near(last(run("ALMA", ohlcv(ramp(50)), [9, 0.5, 6])[0]), 49 - 4, 8);
    near(last(run("T3", ohlcv(cst(100, 3)), [5, 0.7])[0]), 3);
    near(last(run("MCGINLEY", ohlcv(cst(40, 5)), [14])[0]), 5);
  });
  it("SMMA equals Wilder smoothing of a constant", () => near(last(run("SMMA", ohlcv(cst(40, 9)), [14])[0]), 9));
  it("ENV puts bands a percent either side", () => {
    const [m, u, l] = run("ENV", ohlcv(cst(40, 100)), [20, 2.5]);
    near(last(m), 100);
    near(last(u), 102.5);
    near(last(l), 97.5);
  });
});

describe("regression", () => {
  it("fits y = 2x + 3 exactly", () => {
    const c = ohlcv(F(Array.from({ length: 30 }, (_, i) => 2 * i + 3)));
    near(last(run("LSMA", c, [10])[0]), 2 * 29 + 3);
    near(last(run("LRSLOPE", c, [10])[0]), 2);
    near(last(run("LRINTERCEPT", c, [10])[0]), 2 * 20 + 3);
    near(last(run("LRR2", c, [10])[0]), 1);
  });
  it("angle of slope 1 is 45 degrees", () => near(last(run("LRANGLE", ohlcv(ramp(30)), [10])[0]), 45));
});

describe("momentum", () => {
  it("ROC / ROCR / MOM", () => {
    const c = ohlcv(F([100, 110]));
    near(run("ROC", c, [1])[0][1], 10);
    near(run("ROCR", c, [1])[0][1], 1.1);
    near(run("MOM", c, [1])[0][1], 10);
  });
  it("TRIX, PPO, APO, KST, Coppock are zero on a constant", () => {
    const c = ohlcv(cst(200, 50));
    near(last(run("TRIX", c)[0]), 0);
    near(last(run("PPO", c)[0]), 0);
    near(last(run("APO", c)[0]), 0);
    near(last(run("KST", c)[0]), 0);
    near(last(run("COPPOCK", c)[0]), 0);
  });
  it("CMO is 100 when every bar rises, TSI is 100 on a ramp", () => {
    near(last(run("CMO", ohlcv(ramp(40)), [14])[0]), 100);
    near(last(run("TSI", ohlcv(ramp(100)))[0]), 100);
  });
  it("Ultimate oscillator is 100 when buying pressure equals the true range", () => {
    const c = ramp(60, 1, 10);
    near(last(run("ULTOSC", { o: c, h: c.slice(), l: c.map((x) => x - 0.2), c, v: cst(60, 1) })[0]), 100);
  });
  it("Awesome oscillator on a ramp = 14.5, Accelerator = 0", () => {
    near(last(run("AO", ohlcv(ramp(100)))[0]), 14.5);
    near(last(run("AC", ohlcv(ramp(100)))[0]), 0);
  });
  it("DPO on a ramp = -1.5 for n=20", () => near(last(run("DPO", ohlcv(ramp(100)), [20])[0]), -1.5));
  it("Aroon on rising highs and lows", () => {
    const [up, dn] = run("AROON", ohlcv(ramp(60)), [25]);
    near(last(up), 100);
    near(last(dn), 0);
    near(last(run("AROONOSC", ohlcv(ramp(60)), [25])[0]), 100);
  });
  it("Vortex +VI 1.5, -VI 0.5 on a unit ramp with spread 1", () => {
    const [p, m] = run("VORTEX", ohlcv(ramp(40)), [14]);
    near(last(p), 1.5);
    near(last(m), 0.5);
  });
  it("Balance of power is 1 when close = high and open = low", () => {
    const b: Cols = { o: F([1]), h: F([3]), l: F([1]), c: F([3]), v: F([1]) };
    near(run("BOP", b)[0][0], 1);
  });
  it("Elder Ray on a constant", () => {
    const [bull, bear] = run("ELDER", ohlcv(cst(40, 10)), [13]);
    near(last(bull), 1);
    near(last(bear), -1);
  });
  it("oscillators stay inside their bounds", () => {
    const c = ohlcv(F(Array.from({ length: 400 }, (_, i) => 100 + 10 * Math.sin(i / 7) + (i % 5))));
    for (const id of ["STOCHRSI", "STC", "CRSI", "PRANK", "RVIV", "ULTOSC"]) {
      for (const a of run(id, c)) for (const x of a) if (Number.isFinite(x)) expect(x >= -1e-9 && x <= 100 + 1e-9, `${id} ${x}`).toBe(true);
    }
  });
});

describe("volatility and statistics", () => {
  const sd = ohlcv(F([2, 4, 4, 4, 5, 5, 7, 9]));
  it("STDEV / VAR / Z-score of the classic textbook sample", () => {
    near(last(run("STDEV", sd, [8])[0]), 2);
    near(last(run("VAR", sd, [8])[0]), 4);
    near(last(run("ZSCORE", sd, [8])[0]), 2);
  });
  it("Bollinger %B and bandwidth", () => {
    near(last(run("BBPB", sd, [8, 2])[0]), 1);
    near(last(run("BBW", sd, [8, 2])[0]), 160);
  });
  it("Ulcer index [100, 90, 90]", () => near(last(run("ULCER", ohlcv(F([100, 90, 90])), [2])[0]), Math.sqrt(50)));
  it("Historical volatility is 0 for constant growth", () => near(last(run("HV", ohlcv(F(Array.from({ length: 40 }, (_, i) => 100 * 1.01 ** i))), [20, 252])[0]), 0, 8));
  it("Choppiness on a unit ramp", () => near(last(run("CHOP", ohlcv(ramp(40)), [14])[0]), (100 * Math.log10(28 / 15)) / Math.log10(14)));
  it("Mass index sums a ratio of 1 for a constant range", () => near(last(run("MASS", ohlcv(ramp(80)), [9, 25])[0]), 25));
  it("TR, NATR, range, donchian width", () => {
    const c = ohlcv(ramp(40));
    near(last(run("TR", c)[0]), 2);
    near(last(run("RANGE", c)[0]), 2);
    near(last(run("DONCHW", c, [10])[0]), 11);
    near(last(run("NATR", c, [14])[0]), (100 * 2) / 39);
  });
  it("autocorrelation is 1 on a ramp", () => near(last(run("AUTOCORR", ohlcv(ramp(40)), [10, 1])[0]), 1));
  it("price channel is the previous window's high / low", () => {
    const c = ohlcv(ramp(40));
    near(last(run("PRICECH", c, [10])[0]), 39); // high of bar 38 is 39
  });
  it("highest / lowest / median", () => {
    const c = ohlcv(F([3, 1, 2]));
    near(last(run("MEDIAN", c, [3])[0]), 2);
    near(last(run("HIGHEST", c, [3])[0]), 4);
    near(last(run("LOWEST", c, [3])[0]), 0);
  });
});

describe("volume", () => {
  it("CMF is 1 and ADL is the cumulative volume when every bar closes at its high", () => {
    const c = F([5, 6, 7, 8, 9]);
    const x: Cols = { o: c, h: c.slice(), l: c.map((v) => v - 1), c, v: F([10, 10, 10, 10, 10]) };
    near(last(run("CMF", x, [3])[0]), 1);
    near(last(run("ADL", x)[0]), 50);
  });
  it("Force index and ease of movement on a unit ramp", () => {
    const x = { ...ohlcv(ramp(60)), v: cst(60, 1e6) };
    near(last(run("FORCE", x, [13])[0]), 1e6);
    near(last(run("EOM", x, [14])[0]), 2);
  });
  it("NVI moves only when volume falls, PVI only when it rises", () => {
    const x: Cols = { ...ohlcv(F([100, 110, 121])), v: F([10, 5, 8]) };
    const nvi = run("NVI", x)[0];
    near(nvi[1], 1100);
    near(nvi[2], 1100);
    near(run("PVI", x)[0][1], 1000);
    near(run("PVI", x)[0][2], 1100);
  });
  it("PVT accumulates percent change times volume", () => {
    const x: Cols = { ...ohlcv(F([100, 110])), v: F([5, 7]) };
    near(run("PVT", x)[0][1], 0.7);
  });
  it("Williams A/D", () => {
    const x: Cols = { o: F([10, 12, 11]), h: F([11, 13, 12]), l: F([9, 10, 10]), c: F([10, 12, 11]), v: F([1, 1, 1]) };
    const w = run("WAD", x)[0];
    near(w[1], 2);
    near(w[2], 1);
  });
  it("Chaikin oscillator is flat when ADL is flat", () => {
    const x: Cols = { o: cst(40, 5), h: cst(40, 6), l: cst(40, 4), c: cst(40, 5), v: cst(40, 100) };
    near(last(run("CHAIKINOSC", x)[0]), 0);
  });
  it("close location value", () => near(run("CLV", { o: F([1]), h: F([3]), l: F([1]), c: F([3]), v: F([1]) })[0][0], 1));
});

describe("price transforms and pivots", () => {
  const b: Cols = { o: F([8, 9]), h: F([12, 20]), l: F([8, 4]), c: F([10, 6]), v: F([1, 1]) };
  it("typical, median, weighted, Heikin-Ashi", () => {
    near(run("TYPPRICE", b)[0][0], 10);
    near(run("MEDPRICE", b)[0][0], 10);
    near(run("WCLPRICE", b)[0][0], 10);
    near(run("HAC", b)[0][1], (9 + 20 + 4 + 6) / 4);
    near(run("HAO", b)[0][1], 9.25);
  });
  it("classic pivots from the previous bar (H 12, L 8, C 10)", () => {
    const [p, r1, s1, r2, s2] = run("PIVOT", b).map((a) => a[1]);
    expect([p, r1, s1, r2, s2]).toEqual([10, 12, 8, 14, 6]);
  });
  it("fibonacci pivots", () => {
    const o = run("PIVOTFIB", b).map((a) => a[1]);
    near(o[1], 10 + 0.382 * 4);
    near(o[3], 14);
    near(o[6], 6);
  });
  it("camarilla pivots", () => {
    const o = run("PIVOTCAM", b).map((a) => a[1]);
    near(o[3], 10 + (1.1 * 4) / 2);
    near(o[4], 10 - (1.1 * 4) / 12);
  });
  it("ADXR averages ADX with itself n bars ago", () => {
    const x = ohlcv(F(Array.from({ length: 120 }, (_, i) => 100 + i * 0.5 + Math.sin(i))));
    const adx = run("ADX", x, [14])[0];
    near(last(run("ADXR", x, [14])[0]), (adx[119] + adx[105]) / 2);
  });
});
