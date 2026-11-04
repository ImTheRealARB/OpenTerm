import { describe, expect, it } from "vitest";
import { listenerCount, onIndicatorRequest, requestIndicator } from "./indicatorBus";

describe("indicator bus", () => {
  it("is unanswered without a listener, answered when one returns true", () => {
    expect(requestIndicator({ id: "RSI" })).toBe(false);
    const seen: unknown[] = [];
    const off = onIndicatorRequest((r) => {
      seen.push(r);
      return true;
    });
    expect(requestIndicator({ id: "RSI", params: [21] })).toBe(true);
    expect(requestIndicator({ formula: "close" })).toBe(true);
    expect(seen).toHaveLength(2);
    off();
    expect(listenerCount()).toBe(0);
    expect(requestIndicator({ id: "RSI" })).toBe(false);
  });
  it("a listener that declines (no return) does not count", () => {
    const off = onIndicatorRequest(() => undefined);
    expect(requestIndicator({ id: "ATR" })).toBe(false);
    off();
  });
});
