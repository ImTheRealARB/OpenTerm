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
});
