import { describe, expect, it } from "vitest";
import { atrLast, brickCount, brickText, buildBricks, kagi, lineBreak, pointAndFigure, rangeBars, renko, resolveBox, type SrcBars } from "./bricks";
import { brickNote, isBrickType, volCandleNote } from "./chartTypes";
import { parseGpArgs, serializeGp } from "../functions/gpArgs";

/** Bars from closes alone: open = high = low = close (what the close-only transforms read), times 100, 200, ... */
function fromCloses(c: number[]): SrcBars {
  return { t: c.map((_, i) => (i + 1) * 100), o: c, h: c, l: c, c };
}

describe("ATR and the box", () => {
  it("is the true range when every bar has the same range", () => {
    const n = 20;
    const bars: SrcBars = { t: Array.from({ length: n }, (_, i) => i), o: Array(n).fill(10), h: Array(n).fill(11), l: Array(n).fill(9), c: Array(n).fill(10) };
    expect(atrLast(bars.h, bars.l, bars.c)).toBeCloseTo(2, 9);
    expect(resolveBox(bars)).toEqual({ size: 2, atr: true, period: 14 });
  });
  it("uses the user's BOX when it is a positive number, else falls back to ATR", () => {
    const bars = fromCloses([10, 11, 12]);
    expect(resolveBox(bars, 2.5)).toEqual({ size: 2.5, atr: false, period: 14 });
    expect(resolveBox(bars, -1).atr).toBe(true);
  });
});

describe("renko", () => {
  it("adds a brick per whole box and needs two boxes to reverse", () => {
    // box 1. 11.2 -> brick 10-11; 12.5 -> brick 11-12; 11.4 is only 0.6 below the last close (nothing);
    // 9.9 is 2.1 below it: reversal, first brick opens at the last brick's open (11) and falls to 10.
    const r = renko(fromCloses([10, 10.4, 11.2, 12.5, 11.4, 9.9, 9.1]), 1);
    expect(r.o).toEqual([10, 11, 11]);
    expect(r.c).toEqual([11, 12, 10]);
    expect(r.t).toEqual([300, 400, 600]);
    expect(r.box).toEqual({ size: 1, atr: false, period: 14 });
  });
  it("gives each brick of one source bar its own, increasing time", () => {
    const r = renko(fromCloses([10, 13.5]), 1);
    expect(r.c).toEqual([11, 12, 13]);
    expect(r.t).toEqual([200, 201, 202]);
  });
  it("stops at the mark limit and says so, instead of making millions of bricks", () => {
    const r = renko(fromCloses([100, 200]), 0.0001);
    expect(r.capped).toBe(true);
    expect(brickCount(r)).toBe(100_000);
  });
});

describe("kagi", () => {
  it("turns on a reversal and colours yang above the old shoulder, yin below the old waist", () => {
    // reversal 2. 13 starts a rise (yang). 10.5 is 2.5 under the peak 13: the peak is a point. 9 falls under the old waist 10: yin.
    // 12 is 3 over the low 9: the trough is a point. 14 rises over the old shoulder 13: yang again.
    const k = kagi(fromCloses([10, 11, 13, 12.5, 10.5, 9, 12, 14]), 2);
    expect(k.v).toEqual([10, 13, 9, 14]);
    expect(k.yang).toEqual([true, true, false, true]);
    expect(k.t).toEqual([100, 300, 600, 800]);
  });
  it("has only its first point while price has not moved a full reversal", () => {
    const k = kagi(fromCloses([10, 10.5, 11]), 2);
    expect(k.v).toEqual([10]);
  });
});

describe("point and figure", () => {
  it("builds X and O columns from highs and lows with a 3-box reversal", () => {
    const bars: SrcBars = {
      t: [100, 200, 300, 400, 500, 600],
      o: [10.5, 10.6, 13.0, 12.5, 10.0, 11.0],
      h: [10.5, 13.4, 13.9, 12.8, 10.9, 11.9],
      l: [10.5, 10.6, 12.2, 9.5, 8.2, 9.9],
      c: [10.5, 13.0, 12.5, 10.0, 9.0, 11.5],
    };
    const p = pointAndFigure(bars, 1, 3);
    expect(p.lo).toEqual([10, 8, 9]);
    expect(p.hi).toEqual([14, 13, 12]);
    expect(p.up).toEqual([true, false, true]);
    expect(p.t).toEqual([200, 500, 600]);
    expect(p.box.rev).toBe(3);
  });
});

describe("three line break", () => {
  it("draws a line only when the close passes the last line, and reverses only past the last 3 lines", () => {
    // Three white lines, then closes inside the range (nothing), then 9.5 under the lowest of the last 3 lines (10): a black line from 13.
    const r = lineBreak(fromCloses([10, 11, 12, 13, 12.5, 11.5, 9.5]));
    expect(r.o).toEqual([10, 11, 12, 13]);
    expect(r.c).toEqual([11, 12, 13, 9.5]);
    expect(r.t).toEqual([200, 300, 400, 700]);
    expect(r.box).toBeNull();
  });
  it("continues a falling trend one line at a time", () => {
    const r = lineBreak(fromCloses([10, 9, 8, 8.5, 7]));
    expect(r.c).toEqual([9, 8, 7]);
  });
});

describe("range bars", () => {
  it("walks open, nearer extreme, far extreme, close and closes a bar every full range", () => {
    // One source bar: open 10, high 14, low 9, close 13; the low is nearer the open, so the path is 10, 9, 14, 13. Range 2.
    // 14 is 5 above the low 9: a bar low 9 / close 11, then another bar 11 to 13; the rest (13 to 14) stays unfinished.
    const bars: SrcBars = { t: [100], o: [10], h: [14], l: [9], c: [13] };
    const r = rangeBars(bars, 2);
    expect(r.o).toEqual([10, 11]);
    expect(r.h).toEqual([11, 13]);
    expect(r.l).toEqual([9, 11]);
    expect(r.c).toEqual([11, 13]);
    expect(r.t).toEqual([100, 101]);
  });
});

describe("dispatch, notes and GP tokens", () => {
  it("returns null for a type that is not a brick type", () => {
    expect(buildBricks("CANDLE", fromCloses([1, 2]))).toBeNull();
    expect(isBrickType("RENKO")).toBe(true);
    expect(isBrickType("COLUMNS")).toBe(false);
  });
  it("names the box actually used", () => {
    const box = { size: 2.4137, atr: true, period: 14 };
    expect(brickNote("RENKO", "1d", box)).toBe("RENKO BOX 2.41 (ATR 14) · BUILT FROM 1d BARS · NON-LINEAR TIME AXIS");
    expect(brickNote("PNF", "1d", { ...box, atr: false, rev: 3 })).toBe("P&F BOX 2.41 · 3-BOX REVERSAL · BUILT FROM 1d BARS · NON-LINEAR TIME AXIS");
    expect(brickNote("RENKO", "1d", box, { count: 0, capped: false })).toContain("NOTHING DRAWN");
    expect(brickNote("RANGE", "5m", box)).toContain("INTRABAR PATH ASSUMED");
  });
  it("says how many volume-candle bars have no volume", () => {
    expect(volCandleNote([5, 0, NaN, 3])).toContain("2 BARS WITH NO VOLUME");
    expect(volCandleNote([5, 3])).not.toContain("NO VOLUME");
  });
  it("reads the readout text of a mark", () => {
    const r = renko(fromCloses([10, 11.2]), 1);
    expect(brickText(r, 0, (x) => x.toFixed(2))).toBe("RENKO  O 10.00  C 11.00");
  });
  it("parses and writes BOX= and REV= in the GP arguments", () => {
    const p = parseGpArgs(["1Y", "RENKO", "BOX=2.5", "REV=4"]);
    expect(p.type).toBe("RENKO");
    expect(p.box).toBe(2.5);
    expect(p.rev).toBe(4);
    expect(serializeGp(p)).toEqual(["1Y", "RENKO", "BOX=2.5", "REV=4"]);
    // a bad number is ignored (ATR is used) rather than breaking the command
    expect(parseGpArgs(["BOX=0"]).box).toBeUndefined();
    expect(parseGpArgs(["REV=x"]).rev).toBeUndefined();
  });
});

describe("speed", () => {
  it("builds Renko, Point and Figure and Kagi from 50,000 bars", () => {
    // A seeded random walk with a real high / low around each close (the same walk every run).
    const n = 50_000;
    let seed = 12345;
    const rnd = () => ((seed = (seed * 1664525 + 1013904223) >>> 0) / 4294967296) - 0.5;
    const t = new Float64Array(n);
    const o = new Float64Array(n);
    const h = new Float64Array(n);
    const l = new Float64Array(n);
    const c = new Float64Array(n);
    let px = 100;
    for (let i = 0; i < n; i++) {
      t[i] = 1_600_000_000 + i * 86_400;
      o[i] = px;
      px = Math.max(1, px + rnd() * 2);
      c[i] = px;
      h[i] = Math.max(o[i], c[i]) + Math.abs(rnd());
      l[i] = Math.min(o[i], c[i]) - Math.abs(rnd());
    }
    const bars = { t, o, h, l, c };
    // Warm up once (JIT), then time.
    renko(bars);
    const t0 = performance.now();
    const r = renko(bars);
    const t1 = performance.now();
    const p = pointAndFigure(bars);
    const t2 = performance.now();
    const k = kagi(bars);
    const t3 = performance.now();
    const all = t3 - t0;
    console.log(`bricks 50k bars: renko ${(t1 - t0).toFixed(1)} ms (${r.t.length} bricks), pnf ${(t2 - t1).toFixed(1)} ms (${p.t.length} columns), kagi ${(t3 - t2).toFixed(1)} ms (${k.t.length} points), all three ${all.toFixed(1)} ms`);
    expect(r.t.length).toBeGreaterThan(0);
    expect(p.t.length).toBeGreaterThan(0);
    expect(k.t.length).toBeGreaterThan(0);
  });
});
