import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  buildRowIndex,
  markHits,
  rowIds,
  startAgeRedraw,
  subscriptionKey,
  symbolLayout,
  type VisibilityDoc,
} from "./liveRowsCore";
import { bitHas } from "../state/bitset";
import { NO_SYM, symId } from "../state/symbols";

interface R {
  s?: string;
}
const symOf = (r: R) => r.s;

describe("symbol layout and index", () => {
  it("maps symbols to every row that shows them and skips rows without one", () => {
    const layout = symbolLayout([{ s: "A" }, {}, { s: "B" }, { s: "A" }], symOf);
    expect(layout).toEqual(["A", "", "B", "A"]);
    const ids = rowIds(layout);
    expect(ids[1]).toBe(NO_SYM);
    const idx = buildRowIndex(ids);
    const rowsOf = (id: number) => {
      const out: number[] = [];
      for (let r = idx.head[id]; r >= 0; r = idx.next[r]) out.push(r);
      return out;
    };
    expect(rowsOf(symId("A"))).toEqual([0, 3]);
    expect(rowsOf(symId("B"))).toEqual([2]);
  });

  it("subscribes each symbol once, in first-seen order", () => {
    expect(subscriptionKey(["A", "", "B", "A", "C"])).toBe("A,B,C");
    expect(subscriptionKey(["", ""])).toBe("");
  });

  it("marks the rows to repaint for changed symbols", () => {
    const idx = buildRowIndex(rowIds(["A", "B", "A"]));
    const changed = Uint32Array.of(symId("A"), symId("Z-never-in-grid"));
    expect(markHits(idx, changed, 2)).toBe(2);
    expect([0, 1, 2].map((r) => bitHas(idx.dirty, r))).toEqual([true, false, true]);
    idx.dirty.fill(0);
    expect(markHits(idx, Uint32Array.of(symId("Z-never-in-grid")), 1)).toBe(0);
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
