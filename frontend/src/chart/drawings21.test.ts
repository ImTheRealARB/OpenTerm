// Phase 21 drawing tools: the pure maths behind them (position sizing, regression channel, fib extension, rays,
// parallel channel) and the stored-format rules for the new optional fields. Geometry uses an identity-like Geo:
// x = t, y = 1000 - p (so a higher price is a smaller y, like a real chart).
import { describe, expect, it } from "vitest";
import { DRAW_KINDS, TOOLS, fibExtLevels, parseDrawings, positionStats, prims, regression, type Drawing, type Geo, type Prim } from "./drawings";

const geo: Geo = { toX: (t) => t, toY: (p) => 1000 - p, width: 800, height: 1000, logicalOf: (t) => t / 10, xOfLogical: (l) => l * 10 };
const seg = (p: Prim) => p as Extract<Prim, { k: "seg" }>;

describe("position planner", () => {
  it("long: reward / risk and the size that loses exactly the risk budget at the stop", () => {
    const s = positionStats("LONG", 100, 95, 115, "100000 1");
    expect(s.ok).toBe(true);
    expect(s.rr).toBe(3); // 15 up against 5 down
    expect(s.riskCash).toBe(1000); // 1% of 100,000
    expect(s.size).toBe(200); // 1,000 / 5 per share
  });
  it("short with stop below entry is refused, and no account text still gives reward / risk", () => {
    expect(positionStats("SHORT", 100, 95, 90).ok).toBe(false);
    const s = positionStats("SHORT", 100, 104, 92);
    expect(s.ok && s.rr === 2 && s.size === undefined).toBe(true);
  });
});

describe("regression channel and fib extension", () => {
  it("a straight line has slope 1, intercept 0 and no spread", () => {
    const r = regression([0, 1, 2, 3, 4], 0, 4)!;
    expect(r.b).toBeCloseTo(1, 12);
    expect(r.a).toBeCloseTo(0, 12);
    expect(r.sd).toBeCloseTo(0, 12);
    expect(regression([5], 0, 0)).toBeNull();
  });
  it("extension levels project the first move from the pullback end", () => {
    const lv = fibExtLevels(100, 200, 150); // move of +100, pullback to 150
    expect(lv.find((x) => x.ratio === 1)!.price).toBe(250);
    expect(lv.find((x) => x.ratio === 1.618)!.price).toBeCloseTo(311.8, 9);
  });
});

describe("tool geometry", () => {
  it("a ray runs from its first anchor through the second to the right edge; an extended line spans the width", () => {
    const ray: Drawing = { id: "r", kind: "RAY", pts: [{ t: 100, p: 500 }, { t: 200, p: 600 }] };
    const [s] = prims(ray, geo).map(seg);
    expect([s.x1, s.y1, s.x2]).toEqual([100, 500, 800]);
    expect(s.y2).toBeCloseTo(500 - 700, 9); // -1 px per px over 700 px
    const [x] = prims({ ...ray, kind: "XLINE" }, geo).map(seg);
    expect([x.x1, x.x2]).toEqual([0, 800]);
  });
  it("a parallel channel's second line goes through the third anchor with the same slope", () => {
    const ch: Drawing = { id: "c", kind: "PCHAN", pts: [{ t: 100, p: 500 }, { t: 300, p: 600 }, { t: 200, p: 500 }] };
    const [base, par, mid] = prims(ch, geo).map(seg);
    expect(par.y2 - par.y1).toBeCloseTo(base.y2 - base.y1, 9);
    expect(par.y1 - base.y1).toBe(50); // C sits 50 px below the line at its x
    expect(mid.dash).toBe(true);
  });
  it("every tool's anchor count matches its stored rule and draws without throwing", () => {
    for (const k of DRAW_KINDS) {
      const pts = Array.from({ length: TOOLS[k].max }, (_, i) => ({ t: 100 + i * 50, p: 500 + (i % 2 ? 40 : -20) }));
      expect(() => prims({ id: "x", kind: k, pts, label: "100000 1" }, geo, { t: [100, 150, 200, 250, 300, 350], c: [1, 2, 3, 4, 5, 6] })).not.toThrow();
    }
  });
});

describe("stored format (schema 2)", () => {
  it("keeps label / hidden / locked and the variable-length path, drops a path with too many anchors", () => {
    const path = { id: "p", kind: "PATH", pts: [{ t: 1, p: 1 }, { t: 2, p: 2 }, { t: 3, p: 1 }], label: "zig", hidden: true, locked: true };
    const tooLong = { id: "q", kind: "PATH", pts: Array.from({ length: 11 }, (_, i) => ({ t: i, p: i })) };
    expect(parseDrawings([path, tooLong])).toEqual([path]);
  });
});
