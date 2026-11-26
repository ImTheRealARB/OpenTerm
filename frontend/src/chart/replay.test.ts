import { describe, expect, it } from "vitest";
import type { BarData } from "./chartBase";
import { compute, INDICATORS } from "./indicators";
import { decideExit, emptyBook, exitLevels, fillsCsv, finerBetween, firstReveal, onReveal, parseDay, queue, revealed, unrealized } from "./replay";

function bars(n: number, seed = 1): BarData {
  const t = new Float64Array(n);
  const o = new Float64Array(n);
  const h = new Float64Array(n);
  const l = new Float64Array(n);
  const c = new Float64Array(n);
  const v = new Float64Array(n);
  let x = 100;
  let r = seed;
  for (let i = 0; i < n; i++) {
    r = (r * 16807) % 2147483647; // small deterministic random walk
    const step = ((r % 200) - 100) / 100;
    t[i] = 1_700_000_000 + i * 86_400;
    o[i] = x;
    x = Math.max(1, x + step);
    c[i] = x;
    h[i] = Math.max(o[i], c[i]) + 0.5;
    l[i] = Math.min(o[i], c[i]) - 0.5;
    v[i] = 1000 + (r % 500);
  }
  return { symbol: "T", interval: "1d", tz: "UTC", t, o, h, l, c, v };
}

describe("replay (Phase 24)", () => {
  it("no indicator can see a hidden bar", () => {
    const n = 250;
    const a = bars(400, 7);
    const b = bars(400, 99); // different future...
    for (const k of ["t", "o", "h", "l", "c", "v"] as const) b[k].set(a[k].subarray(0, n)); // ...same first 250 bars
    const sa = revealed(a, n);
    const sb = revealed(b, n);
    for (const ind of INDICATORS) {
      const ra = compute(sa, [ind]);
      const rb = compute(sb, [ind]);
      for (const key of Object.keys(ra)) expect(Array.from(rb[key]), `${ind}.${key}`).toEqual(Array.from(ra[key]));
    }
  });

  it("starts before the chosen day and parses dates strictly", () => {
    const a = bars(10);
    expect(firstReveal(a.t, a.t[4])).toBe(4);
    expect(firstReveal(a.t, 0)).toBe(1);
    expect(parseDay("2024-02-30")).toBeNull();
    expect(parseDay("2024-03-01")).toBe(Date.UTC(2024, 2, 1) / 1000);
  });

  it("fills at the next bar's open and books P&L, long and short", () => {
    const a = bars(5);
    let bk = queue(emptyBook(), "BUY", 10);
    bk = onReveal(bk, a, 1);
    expect(bk.qty).toBe(10);
    expect(bk.avg).toBe(a.o[1]);
    bk = queue(bk, "SELL", 15); // closes 10, opens 5 short
    bk = onReveal(bk, a, 2);
    expect(bk.qty).toBe(-5);
    expect(bk.realized).toBeCloseTo(10 * (a.o[2] - a.o[1]));
    expect(unrealized(bk, a.o[2] - 1)).toBeCloseTo(5);
    bk = onReveal(queue(bk, "FLAT", 0), a, 3);
    expect(bk.qty).toBe(0);
    expect(fillsCsv("T", bk.fills).split("\n")).toHaveLength(4);
  });
});

/** Hand-made bars: t in days, one OHLC per row. */
function ohlc(rows: [number, number, number, number][]): BarData {
  const n = rows.length;
  const t = Float64Array.from(rows, (_, i) => 1_700_000_000 + i * 86_400);
  const col = (k: number) => Float64Array.from(rows, (r) => r[k]);
  return { symbol: "T", interval: "1d", tz: "UTC", t, o: col(0), h: col(1), l: col(2), c: col(3), v: new Float64Array(n) };
}

describe("replay stop and target exits (the backtester's rule, mirrored from bt/stops.py)", () => {
  it("levels: a long's stop is below, a short's stop is above", () => {
    const [ls, lt] = exitLevels(100, 1, { stop: 5, target: 10 });
    expect(ls).toBeCloseTo(95);
    expect(lt).toBeCloseTo(110);
    const [s, t] = exitLevels(100, -1, { stop: 5, target: 10 });
    expect(s).toBeCloseTo(105);
    expect(t).toBeCloseTo(90);
    expect(exitLevels(100, 1, {})).toEqual([null, null]);
  });

  it("decideExit gives the same answers as stops.decide (test_phase26)", () => {
    const [stop, target] = exitLevels(100, 1, { stop: 5, target: 10 });
    expect(decideExit(1, 100, 104, 96, stop, target, null)).toBeNull();
    expect(decideExit(1, 100, 104, 94, stop, target, null)).toEqual(["STOP", stop, "single"]);
    expect(decideExit(1, 93, 104, 90, stop, target, null)).toEqual(["STOP", 93, "gap"]);
    expect(decideExit(1, 100, 112, 94, stop, target, null)).toEqual(["STOP", stop, "stop_first"]);
    expect(decideExit(1, 100, 112, 94, stop, target, [[103, 99], [111, 101], [101, 94]])).toEqual(["TARGET", target, "intrabar"]);
    expect(decideExit(1, 100, 112, 94, stop, target, [[112, 94]])).toEqual(["STOP", stop, "stop_first"]);
    const [ss, st] = exitLevels(100, -1, { stop: 5, target: 10 });
    expect(decideExit(-1, 100, 106, 99, ss, st, null)).toEqual(["STOP", ss, "single"]);
  });

  it("closes the practice position at the level and keeps the books straight", () => {
    // bar 0 quiet; bar 1 opens 100 (the buy fills there) and runs to 111 -> the 10% target hits at 110 on the same bar
    const a = ohlc([[100, 101, 99, 100], [100, 111, 99, 108], [108, 109, 107, 108]]);
    let bk = queue(emptyBook(), "BUY", 10);
    bk = onReveal(bk, a, 1, { stop: 5, target: 10 });
    expect(bk.qty).toBe(0);
    expect(bk.fills.map((f) => [f.side, f.why])).toEqual([["BUY", undefined], ["SELL", "TARGET"]]);
    expect(bk.fills[1].price).toBeCloseTo(110);
    expect(bk.realized).toBeCloseTo(100);
    expect(bk.stats).toEqual({ gap: 0, single: 1, intrabar: 0, stop_first: 0 });
    // the next bar must not buy back: the order was one-shot
    expect(onReveal(bk, a, 2, { stop: 5, target: 10 }).fills).toHaveLength(2);
  });

  it("a bar that reached both levels: stop first with no finer bars, finer bars decide when given", () => {
    const a = ohlc([[100, 101, 99, 100], [100, 112, 94, 100]]);
    const stopFirst = onReveal(queue(emptyBook(), "BUY", 10), a, 1, { stop: 5, target: 10 });
    expect(stopFirst.fills[1]).toMatchObject({ side: "SELL", why: "STOP" });
    expect(stopFirst.fills[1].price).toBeCloseTo(95);
    expect(stopFirst.stats.stop_first).toBe(1);
    const asked: number[][] = [];
    const viaFiner = onReveal(queue(emptyBook(), "BUY", 10), a, 1, { stop: 5, target: 10 }, (from, to) => {
      asked.push([from, to]);
      return [[103, 99], [111, 101], [101, 94]];
    });
    expect(viaFiner.fills[1]).toMatchObject({ side: "SELL", why: "TARGET" });
    expect(viaFiner.fills[1].price).toBeCloseTo(110);
    expect(viaFiner.stats.intrabar).toBe(1);
    expect(asked[0][1] - asked[0][0]).toBe(86_400); // the last bar's length is the one before it
  });

  it("a short exits the other way; a gap exits at the open; no exits set changes nothing", () => {
    const a = ohlc([[100, 101, 99, 100], [100, 100.5, 99, 100], [110, 111, 109, 110]]);
    let bk = onReveal(queue(emptyBook(), "SELL", 10), a, 1, { stop: 5 });
    expect(bk.qty).toBe(-10);
    bk = onReveal(bk, a, 2, { stop: 5 }); // opens at 110, above the 105 stop: the exit is the open, not 105
    expect(bk.fills[1]).toMatchObject({ side: "BUY", price: 110, why: "STOP" });
    expect(bk.stats.gap).toBe(1);
    expect(bk.realized).toBeCloseTo(-100);
    const open = onReveal(queue(emptyBook(), "BUY", 10), ohlc([[100, 101, 99, 100], [100, 150, 1, 100]]), 1);
    expect(open.qty).toBe(10);
  });

  it("finerBetween takes the finer bars that START inside the bar, in order, skipping missing values", () => {
    const t = [10, 11, 12, 13, 20];
    const h = [5, null, 7, 8, 9];
    const l = [1, 2, 3, 4, 5];
    expect(finerBetween(t, h, l, 11, 20)).toEqual([[7, 3], [8, 4]]);
    expect(finerBetween(t, h, l, 0, 10)).toEqual([]);
  });
});
