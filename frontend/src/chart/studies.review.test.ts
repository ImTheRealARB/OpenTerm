import { describe, expect, it } from "vitest";
import { mfi, obv } from "./studies";
import { clampIndex, listKey } from "./chartGuards";

const f = (a: number[]) => Float64Array.from(a);

describe("volume studies with a missing volume bar", () => {
  it("OBV treats a NaN volume as zero instead of poisoning every later bar", () => {
    const c = f([10, 11, 12, 11, 13]);
    const v = f([100, NaN, 50, 20, 30]);
    expect(Array.from(obv(c, v))).toEqual([0, 0, 50, 30, 60]);
  });

  it("MFI stays finite when one volume is NaN", () => {
    const n = 20;
    const h = new Float64Array(n), l = new Float64Array(n), c = new Float64Array(n), v = new Float64Array(n);
    for (let i = 0; i < n; i++) {
      c[i] = 100 + (i % 3) + i * 0.1;
      h[i] = c[i] + 1;
      l[i] = c[i] - 1;
      v[i] = 1000;
    }
    v[5] = NaN;
    const out = mfi(h, l, c, v, 14);
    for (let i = 14; i < n; i++) expect(Number.isFinite(out[i])).toBe(true);
  });
});

describe("chart guards", () => {
  it("clampIndex keeps a stale keyboard-crosshair index inside the data", () => {
    expect(clampIndex(4999, 250)).toBe(249);
    expect(clampIndex(-3, 250)).toBe(0);
    expect(clampIndex(7, 250)).toBe(7);
    expect(clampIndex(5, 0)).toBe(-1);
  });

  it("listKey is equal for equal contents, so an inline [] prop does not rebuild the chart each render", () => {
    expect(listKey([])).toBe(listKey([]));
    expect(listKey(["RSI", "MACD"])).toBe(listKey(["RSI", "MACD"]));
    expect(listKey(["RSI", "MACD"])).not.toBe(listKey(["MACD", "RSI"]));
    expect(listKey(["RSI"])).not.toBe(listKey([]));
  });
});
