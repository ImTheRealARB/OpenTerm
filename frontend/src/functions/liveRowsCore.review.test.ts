import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  buildSymbolIndex,
  cachedIndex,
  hitRows,
  sameLayout,
  startAgeRedraw,
  subscriptionKey,
  symbolLayout,
  type IndexCache,
  type VisibilityDoc,
} from "./liveRowsCore";

interface R {
  s?: string;
}
const symOf = (r: R) => r.s;

describe("symbol layout and index", () => {
  it("maps symbols to every row that shows them and skips rows without one", () => {
    const layout = symbolLayout([{ s: "A" }, {}, { s: "B" }, { s: "A" }], symOf);
    expect(layout).toEqual(["A", "", "B", "A"]);
    const idx = buildSymbolIndex(layout);
    expect(idx.get("A")).toEqual([0, 3]);
    expect(idx.get("B")).toEqual([2]);
    expect(idx.has("")).toBe(false);
  });

  it("subscribes each symbol once, in first-seen order", () => {
    expect(subscriptionKey(["A", "", "B", "A", "C"])).toBe("A,B,C");
    expect(subscriptionKey(["", ""])).toBe("");
  });

  it("returns the rows to repaint for changed symbols", () => {
    const idx = buildSymbolIndex(["A", "B", "A"]);
    expect(hitRows(idx, new Set(["A", "Z"]))).toEqual([0, 2]);
    expect(hitRows(idx, new Set(["Z"]))).toEqual([]);
  });

  it("reuses the index while the layout is unchanged and rebuilds when a symbol moves", () => {
    const cache: { current: IndexCache | null } = { current: null };
    const a = cachedIndex(cache, ["A", "B"]);
    expect(cachedIndex(cache, ["A", "B"])).toBe(a); // new array, same symbols: same index
    const b = cachedIndex(cache, ["B", "A"]); // sorted: positions changed
    expect(b).not.toBe(a);
    expect(b.get("A")).toEqual([1]);
    expect(cachedIndex(cache, ["B", "A", "C"])).not.toBe(b);
    expect(sameLayout(["A"], ["A", ""])).toBe(false);
  });
});

describe("startAgeRedraw", () => {
  let hidden = false;
  let listener: (() => void) | undefined;
  const doc: VisibilityDoc = {
    get hidden() {
      return hidden;
    },
    addEventListener: (_t, fn) => {
      listener = fn;
    },
    removeEventListener: (_t, fn) => {
      if (listener === fn) listener = undefined;
    },
  };
  const setHidden = (h: boolean) => {
    hidden = h;
    listener?.();
  };

  beforeEach(() => {
    vi.useFakeTimers();
    hidden = false;
    listener = undefined;
  });
  afterEach(() => vi.useRealTimers());

  it("redraws every interval while visible", () => {
    const redraw = vi.fn();
    startAgeRedraw(redraw, 5000, doc);
    vi.advanceTimersByTime(15000);
    expect(redraw).toHaveBeenCalledTimes(3);
  });

  it("does not redraw while hidden, redraws once on return, then resumes", () => {
    const redraw = vi.fn();
    startAgeRedraw(redraw, 5000, doc);
    setHidden(true);
    vi.advanceTimersByTime(60000);
    expect(redraw).not.toHaveBeenCalled();
    setHidden(false);
    expect(redraw).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(5000);
    expect(redraw).toHaveBeenCalledTimes(2);
  });

  it("starts idle when the page is already hidden", () => {
    const redraw = vi.fn();
    hidden = true;
    startAgeRedraw(redraw, 5000, doc);
    vi.advanceTimersByTime(20000);
    expect(redraw).not.toHaveBeenCalled();
  });

  it("stops the timer and the listener on cleanup", () => {
    const redraw = vi.fn();
    const stop = startAgeRedraw(redraw, 5000, doc);
    stop();
    expect(listener).toBeUndefined();
    vi.advanceTimersByTime(20000);
    expect(redraw).not.toHaveBeenCalled();
  });

  it("works without a document", () => {
    const redraw = vi.fn();
    const stop = startAgeRedraw(redraw, 5000, undefined);
    vi.advanceTimersByTime(5000);
    expect(redraw).toHaveBeenCalledTimes(1);
    stop();
  });
});
