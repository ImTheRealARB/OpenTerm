import { describe, expect, it } from "vitest";
import { adx, atr, cci, donchian, ichimoku, keltner, mfi, obv, psar, stoch, supertrend, willr } from "./studies";
import { compute, INDICATORS } from "./indicators";

const f = (a: number[]) => Float64Array.from(a);
const close = (a: number, b: number, d = 6) => expect(a).toBeCloseTo(b, d);
const nan = (a: number) => expect(Number.isNaN(a)).toBe(true);

const H = f([10, 12, 11, 13]);
const L = f([8, 9, 9, 10]);
const C = f([9, 11, 10, 12]);

describe("studies (golden values worked by hand)", () => {
  it("atr is Wilder's average of true range", () => {
    const r = atr(H, L, C, 2);
    nan(r[0]);
    close(r[1], 2.5);
    close(r[2], 2.25);
    close(r[3], 2.625);
  });

  it("stoch %K and %D", () => {
    const r = stoch(H, L, C, 3, 2);
    nan(r.k[1]);
    close(r.k[2], 50);
    close(r.k[3], 75);
    nan(r.d[2]);
    close(r.d[3], 62.5);
  });

  it("stoch on a flat window is 50, not NaN", () => {
    const r = stoch(f([5, 5, 5]), f([5, 5, 5]), f([5, 5, 5]), 3, 1);
    close(r.k[2], 50);
  });

  it("obv adds volume on up closes and subtracts on down closes", () => {
    const r = obv(f([10, 11, 10, 10, 12]), f([100, 200, 300, 400, 500]));
    expect(Array.from(r)).toEqual([0, 200, -100, -100, 400]);
  });

  it("willr", () => {
    const r = willr(H, L, C, 3);
    close(r[2], -50);
    close(r[3], -25);
  });

  it("cci", () => {
    close(cci(f([1, 2, 3]), f([1, 2, 3]), f([1, 2, 3]), 3)[2], 100);
    close(cci(f([3, 5, 1]), f([3, 5, 1]), f([3, 5, 1]), 3)[2], -100);
    nan(cci(f([1, 2, 3]), f([1, 2, 3]), f([1, 2, 3]), 3)[1]);
  });

  it("mfi", () => {
    const c = f([10, 11, 10, 12]);
    const r = mfi(c, c, c, f([1, 2, 3, 4]), 2);
    nan(r[1]);
    close(r[2], 100 - 100 / (1 + 22 / 30));
    close(r[3], 100 - 100 / (1 + 48 / 30));
  });

  it("keltner bands on a constant-range series", () => {
    const c = f(Array(6).fill(10));
    const k = keltner(f(Array(6).fill(11)), f(Array(6).fill(9)), c, 3, 3, 2);
    close(k.mid[5], 10);
    close(k.upper[5], 14);
    close(k.lower[5], 6);
    nan(k.mid[1]);
  });

  it("donchian channel", () => {
    const d = donchian(f([1, 3, 2, 5, 4]), f([0, 1, 1, 2, 3]), 3);
    expect([d.upper[2], d.lower[2], d.mid[2]]).toEqual([3, 0, 1.5]);
    expect([d.upper[3], d.lower[3]]).toEqual([5, 1]);
    expect([d.upper[4], d.lower[4]]).toEqual([5, 1]);
    nan(d.upper[1]);
  });

  it("psar golden start", () => {
    const r = psar(f([10, 11, 12, 13]), f([9, 10, 11, 12]));
    nan(r[0]);
    close(r[1], 9);
    close(r[2], 9);
    close(r[3], 9.18);
  });

  it("psar flips above price after a reversal", () => {
    const h = [10, 11, 12, 13, 14, 15, 14, 12, 10, 8, 6, 4];
    const l = h.map((x) => x - 1);
    const r = psar(f(h), f(l));
    const last = r.length - 1;
    expect(r[last]).toBeGreaterThan(h[last]);
    expect(r[4]).toBeLessThan(l[4]);
  });

  it("supertrend is up (line under price) in an up trend and flips on a crash", () => {
    const n = 40;
    const c: number[] = [];
    for (let i = 0; i < n; i++) c.push(100 + i * 2);
    for (let i = 0; i < 15; i++) c.push(c[c.length - 1] - 6);
    const h = c.map((x) => x + 1);
    const l = c.map((x) => x - 1);
    const s = supertrend(f(h), f(l), f(c), 10, 3);
    expect(s.dir[n - 1]).toBe(1);
    expect(s.line[n - 1]).toBeLessThan(c[n - 1]);
    expect(s.dir[c.length - 1]).toBe(-1);
    expect(s.line[c.length - 1]).toBeGreaterThan(c[c.length - 1]);
    nan(s.line[0]);
  });

  it("adx is high and +DI leads in a strong trend, low in a range", () => {
    const up = Array.from({ length: 60 }, (_, i) => 100 + i * 2);
    const a = adx(f(up.map((x) => x + 1)), f(up.map((x) => x - 1)), f(up), 14);
    nan(a.adx[2 * 14 - 2]);
    expect(Number.isFinite(a.adx[2 * 14 - 1])).toBe(true);
    expect(a.adx[59]).toBeGreaterThan(40);
    expect(a.pdi[59]).toBeGreaterThan(a.mdi[59]);
    const wave = Array.from({ length: 80 }, (_, i) => 100 + (i % 2 ? 1 : -1));
    const b = adx(f(wave.map((x) => x + 1)), f(wave.map((x) => x - 1)), f(wave), 14);
    expect(b.adx[79]).toBeLessThan(15);
  });

  it("ichimoku lines with small periods", () => {
    const x = f(Array.from({ length: 12 }, (_, i) => i + 1));
    const r = ichimoku(x, x, x, 3, 5, 7, 2);
    close(r.tenkan[2], 2);
    nan(r.tenkan[1]);
    close(r.kijun[4], 3);
    nan(r.spanA[5]);
    close(r.spanA[6], 3.5);
    nan(r.spanB[7]);
    close(r.spanB[8], 4);
    close(r.chikou[0], 3);
    nan(r.chikou[11]);
    nan(r.chikou[10]);
  });

  it("compute() serves the new studies by name with aligned arrays", () => {
    const n = 80;
    const c = Float64Array.from({ length: n }, (_, i) => 100 + Math.sin(i / 5) * 5 + i * 0.1);
    const s = {
      t: Float64Array.from({ length: n }, (_, i) => 1_700_000_000 + i * 86400),
      o: c.map((x) => x - 0.2),
      h: c.map((x) => x + 1),
      l: c.map((x) => x - 1),
      c,
      v: Float64Array.from({ length: n }, (_, i) => 1000 + i),
    };
    for (const name of ["ATR", "STOCH", "ADX", "OBV", "CCI", "WILLR", "MFI", "KELT", "DONCH", "SUPERTREND", "PSAR", "ICHIMOKU", "PAT:CANDLE", "PAT:SMC"] as const) {
      expect(INDICATORS).toContain(name);
      const r = compute(s, [name]);
      const keys = Object.keys(r);
      expect(keys.length).toBeGreaterThan(0);
      for (const k of keys) if (k !== "SMC_ZONES") expect(r[k].length).toBe(n);
    }
  });
});
