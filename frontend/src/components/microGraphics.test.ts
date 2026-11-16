import { describe, expect, it } from "vitest";
import { BAR_FULL_PCT, CLOSED_AFTER_S, barSpan, sparkBounds, sparkX, sparkY, statusFlag, type Bounds } from "./microGraphics";

describe("barSpan", () => {
  it("grows right for a rise and left for a fall, from the centre", () => {
    const up = barSpan(1.5, 60)!;
    const down = barSpan(-1.5, 60)!;
    expect(up.up).toBe(true);
    expect(up.x).toBe(30); // starts at the centre
    expect(down.up).toBe(false);
    expect(down.x + down.w).toBe(30); // ends at the centre
    expect(up.w).toBeCloseTo(down.w);
  });
  it("is full half-width at BAR_FULL_PCT and clamped above it", () => {
    const full = barSpan(BAR_FULL_PCT, 60)!;
    expect(full.w).toBe(28); // half (30) minus the 2px inset
    expect(barSpan(BAR_FULL_PCT * 10, 60)!.w).toBe(full.w);
    expect(barSpan(-BAR_FULL_PCT * 10, 60)!.x).toBe(2); // a big fall reaches the left inset
  });
  it("scales linearly below the clamp", () => {
    expect(barSpan(BAR_FULL_PCT / 2, 60)!.w).toBeCloseTo(14);
  });
  it("is at least one pixel for a real but tiny move", () => {
    expect(barSpan(0.0001, 60)!.w).toBe(1);
  });
  it("draws nothing for zero, null, NaN, infinity or a cell too narrow", () => {
    expect(barSpan(0, 60)).toBeNull();
    expect(barSpan(null, 60)).toBeNull();
    expect(barSpan(undefined, 60)).toBeNull();
    expect(barSpan(NaN, 60)).toBeNull();
    expect(barSpan(Infinity, 60)).toBeNull();
    expect(barSpan(1, 4)).toBeNull();
  });
});

describe("sparkBounds / sparkY / sparkX", () => {
  const out = (): Bounds => ({ min: 0, max: 0, n: 0 });
  it("finds min and max over finite points and skips the rest", () => {
    const b = sparkBounds([3, NaN, 1, Infinity, 2], null, out());
    expect(b).toEqual({ min: 1, max: 3, n: 3 });
  });
  it("lets the live price replace the last point", () => {
    expect(sparkBounds([1, 2, 3], 10, out())).toEqual({ min: 1, max: 10, n: 3 });
    expect(sparkBounds([1, 2, 3], NaN, out())).toEqual({ min: 1, max: 3, n: 3 }); // a bad live value is ignored, not drawn
  });
  it("reports no points for an empty series", () => {
    expect(sparkBounds([], 5, out()).n).toBe(0);
  });
  it("puts max at the top pad and min at the bottom pad", () => {
    expect(sparkY(10, 0, 10, 20, 2)).toBe(2);
    expect(sparkY(0, 0, 10, 20, 2)).toBe(18);
    expect(sparkY(5, 0, 10, 20, 2)).toBe(10);
  });
  it("draws a flat series on the middle line", () => {
    expect(sparkY(7, 7, 7, 20, 2)).toBe(10);
  });
  it("spreads x evenly with padding, and centres a single point", () => {
    expect(sparkX(0, 5, 50, 2)).toBe(2);
    expect(sparkX(4, 5, 50, 2)).toBe(48);
    expect(sparkX(2, 5, 50, 2)).toBe(25);
    expect(sparkX(0, 1, 50, 2)).toBe(25);
  });
});

describe("statusFlag", () => {
  const base = { missing: false, live: false, stale: false, tradeTime: 1_000_000, now: 1_000_000 };
  it("is blank for any live tick, whatever the source", () => {
    expect(statusFlag({ ...base, live: true })).toBe("");
    expect(statusFlag({ ...base, live: true, stale: true, tradeTime: 0 })).toBe("");
  });
  it("is d for a stale snapshot", () => {
    expect(statusFlag({ ...base, stale: true })).toBe("d");
  });
  it("is c when a fresh snapshot's last trade is older than the closed threshold", () => {
    expect(statusFlag({ ...base, now: base.tradeTime + CLOSED_AFTER_S + 1 })).toBe("c");
    expect(statusFlag({ ...base, now: base.tradeTime + CLOSED_AFTER_S })).toBe("");
  });
  it("is blank when the trade time is unknown (it cannot tell)", () => {
    expect(statusFlag({ ...base, tradeTime: null, now: 9_999_999 })).toBe("");
  });
  it("is blank for a missing quote", () => {
    expect(statusFlag({ ...base, missing: true, stale: true })).toBe("");
  });
});
