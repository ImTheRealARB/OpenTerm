import { describe, expect, it } from "vitest";
import { bollinger, ema, macd, rsi, sma, vwap } from "./indicators";

const f = (a: number[]) => Float64Array.from(a);
const close = (a: number, b: number) => expect(a).toBeCloseTo(b, 6);

describe("indicators", () => {
  it("sma", () => {
    const r = sma(f([1, 2, 3, 4, 5]), 3);
    expect(Number.isNaN(r[1])).toBe(true);
    expect(Array.from(r.slice(2))).toEqual([2, 3, 4]);
  });

  it("ema seeds with SMA then smooths", () => {
    const r = ema(f([1, 2, 3, 4, 5]), 3);
    expect(r[2]).toBe(2);
    close(r[3], 4 * 0.5 + 2 * 0.5);
    close(r[4], 5 * 0.5 + 3 * 0.5);
  });

  it("bollinger bands of a constant series collapse", () => {
    const b = bollinger(f(Array(25).fill(10)), 20, 2);
    expect(b.upper[24]).toBe(10);
    expect(b.lower[24]).toBe(10);
  });

  it("bollinger uses population SD", () => {
    const b = bollinger(f([2, 4, 4, 4, 5, 5, 7, 9]), 8, 2); // classic example: mean 5, SD 2
    close(b.mid[7], 5);
    close(b.upper[7], 9);
    close(b.lower[7], 1);
  });

  it("rsi extremes and known value", () => {
    expect(rsi(f(Array.from({ length: 20 }, (_, i) => i)), 14)[19]).toBe(100);
    expect(rsi(f(Array.from({ length: 20 }, (_, i) => -i)), 14)[19]).toBe(0);
    // Wilder's sample prices rounded to 2dp. By hand: avg gain 3.34/14, avg loss 1.40/14,
    // RS 2.3857, RSI 70.464 (textbooks print 70.53 because they use the unrounded prices).
    const data = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.1, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28];
    expect(rsi(f(data), 14)[14]).toBeCloseTo(100 - 100 / (1 + 3.34 / 1.4), 6);
  });

  it("macd line is fast EMA minus slow EMA, histogram is line minus signal", () => {
    const src = f(Array.from({ length: 60 }, (_, i) => 100 + Math.sin(i / 5) * 10));
    const m = macd(src);
    const f12 = ema(src, 12);
    const s26 = ema(src, 26);
    close(m.line[40], f12[40] - s26[40]);
    expect(Number.isNaN(m.signal[30])).toBe(true);
    close(m.hist[50], m.line[50] - m.signal[50]);
  });

  it("vwap resets each session", () => {
    const t = f([0, 60, 120, 100000, 100060]);
    const p = f([10, 20, 30, 50, 50]);
    const v = f([1, 1, 2, 1, 1]);
    const r = vwap(t, p, p, p, v);
    close(r[2], (10 + 20 + 60) / 4);
    close(r[3], 50); // new session
  });
});
