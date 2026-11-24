import { describe, expect, it } from "vitest";
import type { BarData } from "./chartBase";
import { compute, INDICATORS } from "./indicators";
import { emptyBook, fillsCsv, firstReveal, onReveal, parseDay, queue, revealed, unrealized } from "./replay";

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
