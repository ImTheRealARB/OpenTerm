import { describe, expect, it } from "vitest";
import { candlePatterns, PATTERN_INFO, smc } from "./patterns";

interface Bar { o: number; h: number; l: number; c: number }

/** Four prefix bars: closes 20,19,18,17 (down) or 17,18,19,20 (up), body 0.5, shadows 0.2. */
function prefix(dir: "down" | "up" | "flat"): Bar[] {
  const closes = dir === "down" ? [20, 19, 18, 17] : dir === "up" ? [17, 18, 19, 20] : [20, 20, 20, 20];
  return closes.map((c) => {
    const o = dir === "up" ? c - 0.5 : c + 0.5;
    return { o, c, h: Math.max(o, c) + 0.2, l: Math.min(o, c) - 0.2 };
  });
}
const cols = (b: Bar[]) => ({
  o: Float64Array.from(b.map((x) => x.o)),
  h: Float64Array.from(b.map((x) => x.h)),
  l: Float64Array.from(b.map((x) => x.l)),
  c: Float64Array.from(b.map((x) => x.c)),
});
const run = (b: Bar[]) => {
  const x = cols(b);
  return Array.from(candlePatterns(x.o, x.h, x.l, x.c));
};
const code = (name: string) => Number(Object.entries(PATTERN_INFO).find(([, v]) => v.name === name)![0]);

describe("candlestick patterns (truth tables)", () => {
  it("names and directions", () => {
    expect(PATTERN_INFO[code("HAMMER")].dir).toBe(1);
    expect(PATTERN_INFO[code("SHOOTING STAR")].dir).toBe(-1);
    expect(PATTERN_INFO[code("DOJI")].dir).toBe(0);
  });

  it("prefix bars alone produce nothing", () => {
    expect(run(prefix("down")).every((v) => v === 0)).toBe(true);
    expect(run(prefix("up")).every((v) => v === 0)).toBe(true);
  });

  it("doji needs no trend context", () => {
    const r = run([{ o: 10, h: 11, l: 9, c: 10.05 }]);
    expect(r[0]).toBe(code("DOJI"));
  });

  it("hammer after a down trend, not after a flat one", () => {
    const bar = { o: 16.8, c: 17.0, h: 17.05, l: 15.8 };
    expect(run([...prefix("down"), bar])[4]).toBe(code("HAMMER"));
    expect(run([...prefix("flat"), bar])[4]).toBe(0);
  });

  it("shooting star after an up trend", () => {
    expect(run([...prefix("up"), { o: 20.0, c: 20.2, h: 21.2, l: 19.95 }])[4]).toBe(code("SHOOTING STAR"));
  });

  it("bullish engulfing (down trend) and bearish engulfing (up trend)", () => {
    const bull = run([...prefix("down"), { o: 17.0, c: 16.5, h: 17.1, l: 16.4 }, { o: 16.4, c: 17.2, h: 17.3, l: 16.3 }]);
    expect(bull[5]).toBe(code("BULL ENGULFING"));
    const bear = run([...prefix("up"), { o: 20.0, c: 20.5, h: 20.6, l: 19.9 }, { o: 20.6, c: 19.8, h: 20.7, l: 19.7 }]);
    expect(bear[5]).toBe(code("BEAR ENGULFING"));
    const flat = run([...prefix("flat"), { o: 17.0, c: 16.5, h: 17.1, l: 16.4 }, { o: 16.4, c: 17.2, h: 17.3, l: 16.3 }]);
    expect(flat[5]).toBe(0);
  });

  it("morning star and evening star", () => {
    const morning = run([
      ...prefix("down"),
      { o: 17.0, c: 15.5, h: 17.1, l: 15.4 },
      { o: 15.3, c: 15.4, h: 15.5, l: 15.2 },
      { o: 15.5, c: 16.6, h: 16.7, l: 15.4 },
    ]);
    expect(morning[6]).toBe(code("MORNING STAR"));
    const evening = run([
      ...prefix("up"),
      { o: 20.0, c: 21.5, h: 21.6, l: 19.9 },
      { o: 21.7, c: 21.6, h: 21.8, l: 21.5 },
      { o: 21.5, c: 20.4, h: 21.6, l: 20.3 },
    ]);
    expect(evening[6]).toBe(code("EVENING STAR"));
  });

  it("bullish and bearish harami", () => {
    const bull = run([...prefix("down"), { o: 17, c: 15, h: 17.1, l: 14.9 }, { o: 15.5, c: 16.2, h: 16.3, l: 15.4 }]);
    expect(bull[5]).toBe(code("BULL HARAMI"));
    const bear = run([...prefix("up"), { o: 20, c: 22, h: 22.1, l: 19.9 }, { o: 21.5, c: 20.8, h: 21.6, l: 20.7 }]);
    expect(bear[5]).toBe(code("BEAR HARAMI"));
  });

  it("pattern output is aligned with the input and handles empty input", () => {
    expect(candlePatterns(new Float64Array(0), new Float64Array(0), new Float64Array(0), new Float64Array(0)).length).toBe(0);
  });
});

describe("smart-money structure (smc)", () => {
  it("swing highs and lows with a one-bar fractal", () => {
    const h = Float64Array.from([1, 3, 2, 5, 4, 4.5]);
    const l = Float64Array.from([0, 2, 1, 3, 2, 3]);
    const c = Float64Array.from([0.5, 2.5, 1.5, 4, 3, 4]);
    const r = smc(c, h, l, c, 1);
    expect(Array.from(r.swing)).toEqual([0, 1, -1, 1, -1, 0]);
  });

  it("break of structure and change of character", () => {
    const c = Float64Array.from([1, 3, 2, 5, 4, 6, 5.5, 1.0]);
    const r = smc(c, c, c, c, 1);
    expect(Array.from(r.bos)).toEqual([0, 0, 0, 1, 0, 1, 0, -2]);
  });

  it("order block and fair value gap", () => {
    const o = Float64Array.from([10, 10, 11.5, 9.2, 12.8]);
    const h = Float64Array.from([10.5, 12, 11.6, 13, 13.2]);
    const l = Float64Array.from([9.5, 10, 9, 9.1, 12.5]);
    const c = Float64Array.from([10, 11.5, 9.2, 12.8, 13]);
    const r = smc(o, h, l, c, 1);
    expect(r.swing[1]).toBe(1);
    expect(r.swing[2]).toBe(-1);
    expect(r.bos[3]).toBe(1);
    const ob = r.zones.find((z) => z.kind === "OB");
    expect(ob).toMatchObject({ dir: 1, bot: 9, top: 11.6 });
    const fvg = r.zones.find((z) => z.kind === "FVG");
    expect(fvg).toMatchObject({ dir: 1, bot: 11.6, top: 12.5, filled: false });
  });

  it("a fair value gap is marked filled once price trades back through it", () => {
    const h = Float64Array.from([10, 11, 13, 14, 13]);
    const l = Float64Array.from([9, 10, 12, 13, 10.5]);
    const c = Float64Array.from([9.5, 10.5, 12.5, 13.5, 11]);
    const r = smc(c, h, l, c, 1);
    const fv = r.zones.filter((z) => z.kind === "FVG");
    expect(fv.length).toBe(2);
    expect(fv.find((z) => z.bot === 10)?.filled).toBe(false);
    expect(fv.find((z) => z.bot === 11)?.filled).toBe(true);
  });
});
