import { describe, expect, it } from "vitest";
import { diffIndicators } from "./indicatorDiff";

describe("diffIndicators", () => {
  it("adds only what is new and removes only what is gone", () => {
    expect(diffIndicators(["SMA20", "RSI"], ["SMA20", "RSI", "MACD"])).toEqual({ add: ["MACD"], remove: [] });
    expect(diffIndicators(["SMA20", "RSI"], ["SMA20"])).toEqual({ add: [], remove: ["RSI"] });
    expect(diffIndicators(["SMA20", "RSI"], ["RSI", "BB"])).toEqual({ add: ["BB"], remove: ["SMA20"] });
  });
  it("is empty when nothing changed, handles duplicates and empty sets", () => {
    expect(diffIndicators(["A"], ["A"])).toEqual({ add: [], remove: [] });
    expect(diffIndicators([], ["A", "A"])).toEqual({ add: ["A"], remove: [] });
    expect(diffIndicators(["A"], [])).toEqual({ add: [], remove: ["A"] });
  });
});
