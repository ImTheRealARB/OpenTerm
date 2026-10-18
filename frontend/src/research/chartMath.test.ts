import { describe, expect, it } from "vitest";
import { extentOf, heatLevel, heatRange, heatText, niceTicks, runs, tickLabel } from "./chartMath";

describe("niceTicks", () => {
  it("steps by 1-2-5 and stays inside the range", () => {
    expect(niceTicks(0, 100, 5)).toEqual([0, 20, 40, 60, 80, 100]);
    expect(niceTicks(0.18, 0.42, 4)).toEqual([0.2, 0.3, 0.4]);
    expect(niceTicks(-3, 3, 6)).toEqual([-3, -2, -1, 0, 1, 2, 3]);
  });
  it("handles a flat or reversed range and refuses non-finite ones", () => {
    expect(niceTicks(5, 5)).toEqual([5]);
    expect(niceTicks(10, 0, 5)).toEqual(niceTicks(0, 10, 5));
    expect(niceTicks(NaN, 3)).toEqual([]);
  });
});

describe("extentOf", () => {
  it("covers every drawable point and pads y", () => {
    const e = extentOf([{ name: "a", points: [[1, 10], [2, null], [3, 20]] }, { name: "b", points: [[0, 15]] }])!;
    expect([e.xMin, e.xMax]).toEqual([0, 3]);
    expect(e.yMin).toBeLessThan(10);
    expect(e.yMax).toBeGreaterThan(20);
  });
  it("is null when nothing can be drawn and widens a single x", () => {
    expect(extentOf([{ name: "a", points: [[1, null]] }])).toBeNull();
    const e = extentOf([{ name: "a", points: [[2, 5]] }])!;
    expect(e.xMax - e.xMin).toBe(1);
    expect(e.yMax).toBeGreaterThan(e.yMin);
  });
});

describe("runs", () => {
  it("breaks a line at a null instead of bridging the gap", () => {
    expect(runs([[0, 1], [1, 2], [2, null], [3, 4]])).toEqual([[[0, 1], [1, 2]], [[3, 4]]]);
    expect(runs([[0, null]])).toEqual([]);
  });
});

describe("heat", () => {
  it("range skips empty cells; level is monotone with a floor", () => {
    expect(heatRange([[0.2, null], [0.5, 0.3]])).toEqual([0.2, 0.5]);
    expect(heatRange([[null]])).toBeNull();
    expect(heatLevel(0.2, 0.2, 0.5)).toBeCloseTo(0.12);
    expect(heatLevel(0.5, 0.2, 0.5)).toBeCloseTo(1);
    expect(heatLevel(0.3, 0.2, 0.5)).toBeGreaterThan(heatLevel(0.25, 0.2, 0.5));
    expect(heatLevel(1, 1, 1)).toBe(0.5);
  });
  it("prints cells by unit and leaves a missing cell blank", () => {
    expect(heatText(0.2734, "pct")).toBe("27.3");
    expect(heatText(1234567, "money")).toBe("1.23M");
    expect(heatText(12.345, "num")).toBe("12.35");
    expect(heatText(null, "pct")).toBe("");
  });
});

describe("tickLabel", () => {
  it("is compact", () => {
    expect(tickLabel(1500000)).toBe("1.5M");
    expect(tickLabel(25000)).toBe("25K");
    expect(tickLabel(343.46)).toBe("343");
    expect(tickLabel(0.25)).toBe("0.25");
    expect(tickLabel(0.0123)).toBe("0.0123");
  });
});
