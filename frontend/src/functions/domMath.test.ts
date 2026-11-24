import { describe, expect, it } from "vitest";
import { domRows, heatGrid, MAX_SNAPS, pushSnap, type Snapshot } from "./domMath";

describe("DOM ladder and liquidity heatmap (Phase 23)", () => {
  it("puts asks above bids, highest price on top", () => {
    const rows = domRows([[99, 1], [98, 2]], [[100, 3], [101, 4]], 2);
    expect(rows.map((r) => [r.price, r.side])).toEqual([[101, "ask"], [100, "ask"], [99, "bid"], [98, "bid"]]);
  });

  it("bins resting size per price row and caps the memory", () => {
    const s: Snapshot = { t: 0, bids: [[90, 1], [91, 2]], asks: [[110, 5]] };
    const h = heatGrid([s], 2)!;
    expect(h.cells[0][0]).toBe(3); // 90 and 91 in the lower row
    expect(h.cells[0][1]).toBe(5);
    expect(h.max).toBe(5);
    let list: Snapshot[] = [];
    for (let i = 0; i < MAX_SNAPS + 5; i++) list = pushSnap(list, { ...s, t: i });
    expect(list.length).toBe(MAX_SNAPS);
    expect(list[0].t).toBe(5);
  });
});
