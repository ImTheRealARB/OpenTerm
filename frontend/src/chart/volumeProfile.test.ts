import { describe, expect, it } from "vitest";
import { periods, rowPrice, volumeProfile } from "./volumeProfile";

const f = (xs: number[]) => Float64Array.from(xs);

describe("volume profile (Phase 23)", () => {
  it("spreads volume over each bar's range and finds the POC and a 70% value area", () => {
    // Prices 0..10 in 10 rows. Bar A covers the whole range (10 units = 1 per row); bar B puts 20 into row 5.
    const p = volumeProfile(f([10, 5.5]), f([0, 5.1]), f([10, 20]), 0, 2, 10, 0.7)!;
    expect(p.total).toBe(30);
    expect(p.vol.reduce((a, b) => a + b, 0)).toBeCloseTo(30);
    expect(p.poc).toBe(5);
    expect(rowPrice(p, p.poc)).toBeCloseTo(5.5);
    // 70% of 30 = 21: POC row holds 21 already (20 + 1)
    expect([p.vaLo, p.vaHi]).toEqual([5, 5]);
  });

  it("returns null with no volume and splits sessions at overnight gaps", () => {
    expect(volumeProfile(f([1]), f([1]), f([0]), 0, 1)).toBeNull();
    expect(periods(f([0, 60, 86_400, 86_460]), "SESSION")).toEqual([[0, 2], [2, 4]]);
  });
});
