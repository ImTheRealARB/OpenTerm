import { describe, expect, it } from "vitest";
import { avwap } from "./avwap";

const f = (xs: number[]) => Float64Array.from(xs);

describe("anchored VWAP (Phase 23)", () => {
  it("weights by volume and widens the bands with the spread", () => {
    const t = f([0, 60, 120]);
    const p = f([10, 20, 20]);
    const r = avwap(t, p, p, p, f([1, 1, 2]), "SESSION");
    expect(r.mid[0]).toBe(10);
    expect(r.mid[2]).toBeCloseTo(17.5); // (10 + 20 + 40) / 4
    // sigma^2 = (100 + 400 + 800) / 4 - 17.5^2 = 325 - 306.25 = 18.75
    expect(r.up1[2] - r.mid[2]).toBeCloseTo(Math.sqrt(18.75));
    expect(r.up3[2] - r.mid[2]).toBeCloseTo(3 * Math.sqrt(18.75));
  });

  it("restarts at a session gap and draws nothing before an anchor", () => {
    const t = f([0, 60, 86_400]);
    const p = f([10, 20, 30]);
    expect(avwap(t, p, p, p, f([1, 1, 1]), "SESSION").mid[2]).toBe(30);
    const a = avwap(t, p, p, p, f([1, 1, 1]), "ANCHOR", 60);
    expect(Number.isNaN(a.mid[0])).toBe(true);
    expect(a.mid[2]).toBe(25);
  });
});
