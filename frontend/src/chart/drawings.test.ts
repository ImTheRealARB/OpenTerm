import { describe, expect, it } from "vitest";
import {
  cycleSelection, distToSegment, fibLevels, hitTest, newId, parseDrawings, segments, snapDay, timeToLogical,
  type Drawing, type Geo,
} from "./drawings";

const geo: Geo = { toX: (t) => t, toY: (p) => 1000 - p, width: 800 };
const hline = (id: string, p: number): Drawing => ({ id, kind: "HLINE", pts: [{ t: 100, p }] });
const trend = (id: string, a: [number, number], b: [number, number]): Drawing => ({ id, kind: "TREND", pts: [{ t: a[0], p: a[1] }, { t: b[0], p: b[1] }] });
const fib = (id: string, a: [number, number], b: [number, number]): Drawing => ({ id, kind: "FIB", pts: [{ t: a[0], p: a[1] }, { t: b[0], p: b[1] }] });

describe("fib retracement", () => {
  it("levels run from the end of the move (0%) back to its start (100%)", () => {
    const up = fibLevels(100, 200);
    expect(up.find((l) => l.ratio === 0)!.price).toBe(200);
    expect(up.find((l) => l.ratio === 0.5)!.price).toBe(150);
    expect(up.find((l) => l.ratio === 1)!.price).toBe(100);
    expect(up.find((l) => l.ratio === 0.618)!.price).toBeCloseTo(138.2, 6);
    const down = fibLevels(200, 100);
    expect(down.find((l) => l.ratio === 0.618)!.price).toBeCloseTo(161.8, 6);
    expect(up.map((l) => l.ratio)).toEqual([0, 0.236, 0.382, 0.5, 0.618, 0.786, 1]);
  });
});

describe("time to logical position", () => {
  const times = [100, 200, 300];
  it("interpolates between bars and extrapolates past the ends by one bar step", () => {
    expect(timeToLogical(150, times)).toBe(0.5);
    expect(timeToLogical(100, times)).toBe(0);
    expect(timeToLogical(300, times)).toBe(2);
    expect(timeToLogical(400, times)).toBe(3);
    expect(timeToLogical(0, times)).toBe(-1);
  });
  it("handles one bar and none", () => {
    expect(timeToLogical(55, [100])).toBe(0);
    expect(Number.isNaN(timeToLogical(1, []))).toBe(true);
  });
  it("an anchor keeps its place when the interval changes (daily point shown on a weekly chart)", () => {
    const day = 86400;
    const mon1 = 1_700_000_000 - (1_700_000_000 % day) + 14.5 * 3600; // only the spacing matters
    const daily = Array.from({ length: 10 }, (_, i) => mon1 + i * day);
    const weekly = [mon1, mon1 + 7 * day];
    const wed1 = daily[2];
    expect(timeToLogical(wed1, daily)).toBe(2);
    const w = timeToLogical(wed1, weekly);
    expect(w).toBeGreaterThan(0);
    expect(w).toBeLessThan(1);
    expect(w).toBeCloseTo(2 / 7, 10);
    expect(timeToLogical(mon1 + 7 * day, weekly)).toBe(1);
  });
});

describe("snapping event dates to bars", () => {
  const day = 86400;
  const open = Date.UTC(2026, 6, 27, 13, 30) / 1000; // Mon 2026-07-27 13:30 UTC
  const daily = Array.from({ length: 5 }, (_, i) => open + i * day); // Mon..Fri
  it("a daily bar takes the event of its own date", () => {
    expect(snapDay("2026-07-29", daily, day)).toBe(daily[2]);
    expect(snapDay("2026-07-27", daily, day)).toBe(daily[0]);
    expect(snapDay("2026-07-31", daily, day)).toBe(daily[4]);
  });
  it("dates with no bar are skipped, never moved", () => {
    expect(snapDay("2026-07-26", daily, day)).toBeNull(); // before the first bar
    expect(snapDay("2026-08-01", daily, day)).toBeNull(); // Saturday after the last bar
    expect(snapDay("2026-08-04", daily, day)).toBeNull();
    expect(snapDay("nope", daily, day)).toBeNull();
  });
  it("a weekly bar takes any day of its week", () => {
    const weekly = [open, open + 7 * day, open + 14 * day];
    expect(snapDay("2026-07-29", weekly, 7 * day)).toBe(weekly[0]);
    expect(snapDay("2026-08-03", weekly, 7 * day)).toBe(weekly[1]);
    expect(snapDay("2026-08-12", weekly, 7 * day)).toBe(weekly[2]);
    expect(snapDay("2026-08-25", weekly, 7 * day)).toBeNull();
  });
});

describe("segments and hit testing", () => {
  it("a horizontal line spans the whole width", () => {
    expect(segments(hline("a", 300), geo)).toEqual([{ x1: 0, y1: 700, x2: 800, y2: 700, price: 300 }]);
  });
  it("a trend line is a ray extended to the right edge", () => {
    const [s] = segments(trend("t", [100, 100], [200, 150]), geo);
    expect(s.x1).toBe(100);
    expect(s.x2).toBe(800);
    expect(s.y2).toBeCloseTo(850 - 0.5 * 600, 9); // screen slope -0.5 px per px, from (200, 850)
  });
  it("a fib has a labelled segment per level plus the link between its anchors", () => {
    const s = segments(fib("f", [100, 100], [300, 200]), geo);
    expect(s).toHaveLength(8);
    expect(s.filter((x) => x.label).map((x) => x.label)).toEqual(["0.0%", "23.6%", "38.2%", "50.0%", "61.8%", "78.6%", "100.0%"]);
    expect(s.filter((x) => x.label).every((x) => x.x1 === 100 && x.x2 === 800)).toBe(true);
  });
  it("a drawing whose anchors are off the chart yields nothing", () => {
    expect(segments(hline("a", 1), { ...geo, toY: () => null })).toEqual([]);
    expect(segments(trend("t", [1, 1], [2, 2]), { ...geo, toX: () => null })).toEqual([]);
  });
  it("a drawing still missing an anchor yields nothing (no crash while it is being placed)", () => {
    expect(segments({ id: "p", kind: "TREND", pts: [{ t: 1, p: 1 }] }, geo)).toEqual([]);
    expect(segments({ id: "p", kind: "FIB", pts: [] }, geo)).toEqual([]);
  });
  it("distance to a segment", () => {
    expect(distToSegment(5, 3, { x1: 0, y1: 0, x2: 10, y2: 0 })).toBe(3);
    expect(distToSegment(-4, 3, { x1: 0, y1: 0, x2: 10, y2: 0 })).toBe(5);
    expect(distToSegment(3, 4, { x1: 0, y1: 0, x2: 0, y2: 0 })).toBe(5);
  });
  it("hit test picks the nearest drawing inside the tolerance, else nothing", () => {
    const ds = [hline("a", 300), hline("b", 296), trend("t", [100, 500], [200, 500])];
    expect(hitTest(ds, 400, 701, geo, 6)).toBe("a"); // 1 px from a (y 700), 3 px from b (y 704)
    expect(hitTest(ds, 400, 705, geo, 6)).toBe("b"); // 1 px from b, 5 px from a
    expect(hitTest(ds, 400, 650, geo, 6)).toBeNull();
    expect(hitTest(ds, 400, 500, geo, 6)).toBe("t");
    expect(hitTest([], 1, 1, geo)).toBeNull();
  });
  it("hit test finds a fib level", () => {
    const ds = [fib("f", [100, 100], [300, 200])];
    expect(hitTest(ds, 500, 1000 - 150 + 2, geo, 6)).toBe("f"); // the 50% level is at price 150
    expect(hitTest(ds, 500, 1000 - 250, geo, 6)).toBeNull();
  });
});

describe("storage helpers", () => {
  it("parseDrawings keeps valid entries and drops malformed ones", () => {
    const good = hline("a", 1);
    const out = parseDrawings([good, { id: "x", kind: "RAY", pts: [] }, { id: "y", kind: "TREND", pts: [{ t: 1, p: 1 }] }, { id: "z", kind: "HLINE", pts: [{ t: 1, p: NaN }] }, null, "s"]);
    expect(out).toEqual([good]);
    expect(parseDrawings("nope")).toEqual([]);
    expect(parseDrawings(Array.from({ length: 300 }, (_, i) => hline(`i${i}`, i)))).toHaveLength(200);
  });
  it("newId never repeats an id in use", () => {
    const ds = [hline("d1", 1), hline("d2", 2)];
    const id = newId(ds);
    expect(ds.some((d) => d.id === id)).toBe(false);
    expect(newId([])).toBe("d1");
  });
  it("cycleSelection wraps both ways and starts from nothing", () => {
    const ds = [hline("a", 1), hline("b", 2), hline("c", 3)];
    expect(cycleSelection(ds, null, 1)).toBe("a");
    expect(cycleSelection(ds, null, -1)).toBe("c");
    expect(cycleSelection(ds, "c", 1)).toBe("a");
    expect(cycleSelection(ds, "a", -1)).toBe("c");
    expect(cycleSelection([], "a", 1)).toBeNull();
    expect(cycleSelection(ds, "gone", 1)).toBe("a");
  });
});
