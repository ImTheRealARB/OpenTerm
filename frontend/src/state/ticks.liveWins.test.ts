/** Audit A-1: a stored tick must not override a newer REST snapshot, nor survive a dropped stream. Same stubs as ticks.dod.test.ts. */
import { beforeAll, describe, expect, it } from "vitest";

type Ticks = typeof import("./ticks");
let T: Ticks;
let S: typeof import("./symbols");
const rafQueue: (() => void)[] = [];
const frame = () => {
  for (const cb of rafQueue.splice(0)) cb();
};

beforeAll(async () => {
  const g = globalThis as unknown as Record<string, unknown>;
  g.window = globalThis;
  g.requestAnimationFrame = (cb: () => void) => rafQueue.push(cb);
  T = await import("./ticks");
  S = await import("./symbols");
});

describe("liveWins", () => {
  it("lets a tick beat only a snapshot that is not newer than the tick", () => {
    T.ingest([["LW1", 100, null, null, null, null, null, 1_000_000, "y"]], 1);
    frame();
    const id = S.symId("LW1");
    expect(T.hasLive(id)).toBe(true);
    expect(T.liveWins(id, null)).toBe(true); // the snapshot has no time: keep the tick
    expect(T.liveWins(id, 1_000_000)).toBe(true); // same trade
    expect(T.liveWins(id, 3_600_000)).toBe(false); // REST has a trade an hour newer: it wins
  });

  it("stops preferring ticks while the stream is down and resumes with the next tick", () => {
    T.ingest([["LW2", 50, null, null, null, null, null, 2_000_000, "y"]], 1);
    frame();
    const id = S.symId("LW2");
    T.setStreamUp(false);
    expect(T.liveWins(id, null)).toBe(false);
    T.ingest([["LW2", 51, null, null, null, null, null, 2_000_500, "y"]], 2);
    frame();
    expect(T.liveWins(id, 2_000_000)).toBe(true);
  });

  it("is false for a symbol that never ticked", () => {
    expect(T.liveWins(S.symId("LW_NEVER"), null)).toBe(false);
  });

  // Audit C-06: a tick of the SAME trade as a STALE snapshot brings nothing newer, so it must not replace the STALE label.
  it("does not let an equal-time tick hide a STALE snapshot, but a newer one still wins", () => {
    T.setStreamUp(true);
    T.ingest([["LW3", 10, null, null, null, null, null, 5_000_000, "y"]], 1);
    frame();
    const id = S.symId("LW3");
    expect(T.liveWins(id, 5_000_000, false)).toBe(true); // same trade, snapshot not stale: either is right
    expect(T.liveWins(id, 5_000_000, true)).toBe(false); // same trade, snapshot STALE: show the STALE snapshot
    expect(T.liveWins(id, 4_999_999, true)).toBe(true); // the tick is newer than the stale snapshot: it wins
  });
});

// Audit H-17: readers that call `getLive` directly (FX legs, PORT, LivePrice, chart header) must get the same rule.
describe("getLive", () => {
  it("returns nothing while the stream is down, then the tick again after the next one", () => {
    T.setStreamUp(true);
    T.ingest([["LG1", 7, null, null, null, null, null, 6_000_000, "y"]], 1);
    frame();
    expect(T.getLive("LG1")?.price).toBe(7);
    T.setStreamUp(false);
    expect(T.getLive("LG1")).toBeUndefined();
    T.ingest([["LG1", 8, null, null, null, null, null, 6_000_500, "y"]], 2);
    frame();
    expect(T.getLive("LG1")?.price).toBe(8);
  });

  it("yields to a newer REST snapshot", () => {
    T.setStreamUp(true);
    T.ingest([["LG2", 3, null, null, null, null, null, 7_000_000, "y"]], 1);
    frame();
    expect(T.getLive("LG2", 8_000_000)).toBeUndefined(); // REST traded later than the last tick
    expect(T.getLive("LG2", 6_000_000)?.price).toBe(3);
    expect(T.getLive("LG2", 7_000_000, true)).toBeUndefined(); // equal time and the snapshot is STALE
  });
});
