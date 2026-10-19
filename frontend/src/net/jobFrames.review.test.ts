import { describe, expect, it } from "vitest";
import { applyJobFrame, applyJobFrames, type JobFrameUpdate, type JobRec } from "./jobFrames";

const frame = (id: string, state: JobFrameUpdate["state"], progress: number): JobFrameUpdate => ({ id, kind: "k", state, progress, msg: "", cached: false });

describe("review: one map copy per job frame batch", () => {
  it("applyJobFrames equals applying the frames one by one", () => {
    const start = new Map<string, JobRec>([["a", { ...frame("a", "running", 0.2), seen_at: 1 }]]);
    const batch = [frame("a", "running", 0.5), frame("b", "queued", 0), frame("a", "done", 1), frame("a", "running", 0.9), frame("b", "running", 0.1)];
    const loop = batch.reduce((m, u) => applyJobFrame(m, u, 100), start);
    const once = applyJobFrames(start, batch, 100);
    expect([...once]).toEqual([...loop]);
    expect(start.get("a")?.progress).toBe(0.2); // the input map is not mutated
    expect(once.get("a")?.state).toBe("done"); // a late running frame never moves a finished job back
  });

  it("bench: 300 jobs, 40 frames per flush", () => {
    const base = new Map<string, JobRec>();
    for (let i = 0; i < 300; i++) base.set(`j${i}`, { ...frame(`j${i}`, "running", 0), seen_at: 1 });
    const batch = Array.from({ length: 40 }, (_, i) => frame(`j${i * 7}`, "running", 0.5));
    const time = (f: () => void) => {
      for (let i = 0; i < 50; i++) f(); // warm up
      const t0 = performance.now();
      for (let i = 0; i < 500; i++) f();
      return (performance.now() - t0) / 500;
    };
    const before = time(() => batch.reduce((m, u) => applyJobFrame(m, u, 1), base));
    const after = time(() => applyJobFrames(base, batch, 1));
    console.log(`jobs flush before ${before.toFixed(3)} ms, after ${after.toFixed(3)} ms`);
    expect(after).toBeLessThan(before);
  });
});
