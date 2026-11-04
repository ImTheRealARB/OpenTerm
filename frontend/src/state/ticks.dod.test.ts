/**
 * Behaviour tests for the struct-of-arrays tick store (ticks.ts). ticks.ts needs `window` (perf/metrics) and
 * requestAnimationFrame, which Node lacks, so this file stubs both BEFORE importing it, and drives frames by hand.
 */
import { beforeAll, describe, expect, it } from "vitest";

type Ticks = typeof import("./ticks");
let T: Ticks;
let S: typeof import("./symbols");
const rafQueue: (() => void)[] = [];
/** Run the queued animation-frame callbacks (the flush), the way the browser would. */
const frame = () => {
  const q = rafQueue.splice(0);
  for (const cb of q) cb();
};

beforeAll(async () => {
  const g = globalThis as unknown as Record<string, unknown>;
  g.window = globalThis;
  g.requestAnimationFrame = (cb: () => void) => rafQueue.push(cb);
  T = await import("./ticks");
  S = await import("./symbols");
});

type Row = Parameters<Ticks["ingest"]>[0][number];
const row = (s: string, p: number, extra: Partial<Record<"chg" | "pct" | "vol" | "hi" | "lo", number>> = {}, src = "s"): Row => [
  s, p, extra.chg ?? null, extra.pct ?? null, extra.vol ?? null, extra.hi ?? null, extra.lo ?? null, 1000, src,
];

describe("tick store", () => {
  it("applies the last tick per symbol once per frame and keeps fields a later tick did not carry", () => {
    const seen: number[][] = [];
    const off = T.onTicks((b) => {
      const ids: number[] = [];
      for (let k = 0; k < b.count; k++) ids.push(b.ids[k]);
      seen.push(ids);
    });
    T.ingest([row("AAA", 10, { chg: 1, pct: 11, vol: 500 }), row("BBB", 5), row("AAA", 11)], 1);
    expect(rafQueue.length).toBe(1); // one flush scheduled however many ticks arrive
    frame();
    off();
    expect(seen).toHaveLength(1);
    expect(seen[0].map((id) => S.symName(id))).toEqual(["AAA", "BBB"]); // deduplicated, arrival order
    const a = T.getLive("AAA")!;
    expect(a.price).toBe(11);
    expect(a.change).toBe(1); // carried from the first tick of the frame
    expect(a.volume).toBe(500);
    expect(a.high).toBeNull();
    expect(a.dir).toBe(0); // first sight: no direction yet
    expect(T.getLive("NEVER")).toBeUndefined();
  });

  it("tracks direction, keeps old fields across frames and stamps the frame", () => {
    T.ingest([row("AAA", 12)], 1);
    frame();
    const a = T.getLive("AAA")!;
    expect(a.dir).toBe(1);
    expect(a.change).toBe(1); // not in this tick: unchanged
    expect(a.frame).toBe(T.currentFrame());
    T.ingest([row("AAA", 12)], 1);
    frame();
    expect(a.dir).toBe(1); // flat keeps the last direction
    T.ingest([row("AAA", 9, { chg: -3 })], 1);
    frame();
    expect(a.dir).toBe(-1);
    expect(a.change).toBe(-3);
    expect(T.srcLabel(115)).toBe("SYNTHETIC");
  });

  it("hands raw ticks to listeners as they arrive, duplicates included, and the batch is empty after the frame", () => {
    const prices: number[] = [];
    const offRaw = T.onRawTicks((r) => {
      for (let i = 0; i < r.n; i++) prices.push(r.price[i]);
    });
    let count = -1;
    const off = T.onTicks((b) => {
      count = b.count;
    });
    T.ingest([row("CCC", 1), row("CCC", 2), row("CCC", 3)], 1);
    expect(prices).toEqual([1, 2, 3]); // before any frame
    frame();
    expect(count).toBe(1);
    offRaw();
    off();
    let after = -1;
    const off2 = T.onTicks((b) => {
      after = b.has(S.symId("CCC")) ? 1 : 0;
    });
    T.ingest([row("DDD", 1)], 1);
    frame();
    off2();
    expect(after).toBe(0); // CCC's bit was cleared at the end of the previous frame
  });

  it("grows past the first capacity (many symbols) without losing data", () => {
    const rows: Row[] = [];
    for (let i = 0; i < 1000; i++) rows.push(row(`G${i}`, i + 1));
    T.ingest(rows, 1);
    frame();
    expect(T.getLive("G0")!.price).toBe(1);
    expect(T.getLive("G999")!.price).toBe(1000);
    expect(T.getLive("AAA")!.price).toBe(9); // old data survived the reallocation
  });
});
