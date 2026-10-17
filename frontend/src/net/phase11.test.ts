import { describe, expect, it } from "vitest";

/*
 * Phase 11 pure modules (spec: docs/specs/PHASE_11.md), written before the code.
 * `it.fails` until the module exists; each build step switches its block to `it` and to static imports.
 * The import path is a variable so tsc does not fail on a module that is not written yet.
 */
const load = (path: string): Promise<any> => import(/* @vite-ignore */ path);

describe("jobFrames (step 4)", () => {
  it.fails("parses J frames and ignores everything else", async () => {
    const { parseJobFrame } = await load("./jobFrames");
    expect(parseJobFrame(["J", { id: "a1", kind: "sleep", state: "running", progress: 0.5, msg: "step 3/6", cached: false }]))
      .toEqual({ id: "a1", kind: "sleep", state: "running", progress: 0.5, msg: "step 3/6", cached: false });
    expect(parseJobFrame(["T", []])).toBeNull();
    expect(parseJobFrame(["J", { id: "a1" }])).toBeNull();
    expect(parseJobFrame(["J", { id: "a1", kind: "sleep", state: "weird", progress: 0, msg: "", cached: false }])).toBeNull();
    // progress is clamped to 0..1
    expect(parseJobFrame(["J", { id: "b", kind: "sleep", state: "running", progress: 1.7, msg: "", cached: false }])?.progress).toBe(1);
  });

  it.fails("applies updates in order and never moves a finished job back", async () => {
    const { applyJobFrame } = await load("./jobFrames");
    let jobs = new Map();
    jobs = applyJobFrame(jobs, { id: "a", kind: "sleep", state: "running", progress: 0.2, msg: "", cached: false });
    jobs = applyJobFrame(jobs, { id: "a", kind: "sleep", state: "done", progress: 1, msg: "", cached: false });
    jobs = applyJobFrame(jobs, { id: "a", kind: "sleep", state: "running", progress: 0.4, msg: "late", cached: false });
    expect(jobs.get("a").state).toBe("done");
    expect(jobs.get("a").progress).toBe(1);
  });

  it.fails("renders a text progress bar", async () => {
    const { progressText } = await load("./jobFrames");
    expect(progressText(0.52)).toBe("#####.....  52%");
    expect(progressText(0)).toBe("..........   0%");
    expect(progressText(1)).toBe("########## 100%");
  });
});

describe("KEY REQUIRED envelope (step 3)", () => {
  it.fails("reads the 424 envelope", async () => {
    const { keyRequired } = await load("./keyRequired");
    const body = { error: "KEY REQUIRED", kind: "key_required", key: "FINNHUB", detail: "KEY REQUIRED: set FINNHUB in APIKEYS" };
    expect(keyRequired(424, body)).toEqual({ key: "FINNHUB", detail: "KEY REQUIRED: set FINNHUB in APIKEYS" });
    expect(keyRequired(503, { error: "PROVIDER DOWN", kind: "unavailable" })).toBeNull();
    expect(keyRequired(424, { error: "KEY REQUIRED" })).toBeNull();
  });
});

describe("APIKEYS masking (step 3)", () => {
  it.fails("shows only the last 4 characters while typing", async () => {
    const { maskKey } = await load("../functions/apikeysMask");
    expect(maskKey("sk-or-v1-abcdef1234")).toBe("••••1234");
    expect(maskKey("abc")).toBe("•••");
    expect(maskKey("")).toBe("");
  });
});
