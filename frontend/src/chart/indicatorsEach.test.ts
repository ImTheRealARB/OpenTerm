import { describe, expect, it } from "vitest";
import { compute, computeEach, type IndicatorName, type Series } from "./indicators";

// 60 bars of a gentle wave: enough for every default window.
const N = 60;
const mk = (f: (i: number) => number) => Float64Array.from({ length: N }, (_, i) => f(i));
const series: Series = {
  t: mk((i) => 1_700_000_000 + i * 86400),
  o: mk((i) => 100 + Math.sin(i / 3)),
  h: mk((i) => 102 + Math.sin(i / 3)),
  l: mk((i) => 98 + Math.sin(i / 3)),
  c: mk((i) => 100 + Math.sin(i / 3 + 0.2)),
  v: mk((i) => 1000 + i),
};

describe("computeEach (one worker message, outputs grouped per indicator)", () => {
  const batch: IndicatorName[] = ["SMA20", "BB", "RSI", "MACD", "ICHIMOKU"];

  it("has one group per requested indicator, holding only that indicator's outputs", () => {
    const parts = computeEach(series, batch);
    expect(Object.keys(parts)).toEqual(batch);
    expect(Object.keys(parts.BB ?? {}).sort()).toEqual(["BB_LO", "BB_MID", "BB_UP"]);
    expect(Object.keys(parts.RSI ?? {})).toEqual(["RSI"]);
    expect(Object.keys(parts.SMA20 ?? {})).toEqual(["SMA20"]);
  });

  it("merging the groups gives exactly what one combined compute gives", () => {
    const merged = Object.assign({}, ...Object.values(computeEach(series, batch)));
    const direct = compute(series, batch);
    expect(Object.keys(merged).sort()).toEqual(Object.keys(direct).sort());
    for (const k of Object.keys(direct)) expect(Array.from(merged[k] as Float64Array)).toEqual(Array.from(direct[k]));
  });

  it("an empty request gives an empty result", () => {
    expect(computeEach(series, [])).toEqual({});
  });
});
