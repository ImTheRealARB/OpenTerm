import { describe, expect, it } from "vitest";
import { createSyncGate } from "./syncGate";

describe("createSyncGate", () => {
  it("retries when the link comes up after the first load failed", async () => {
    let calls = 0;
    const gate = createSyncGate(async () => {
      calls++;
      if (calls === 1) throw new Error("backend down");
    });
    await gate.attempt(); // page load, backend down
    expect(gate.loaded()).toBe(false);
    await gate.onLink("DOWN");
    expect(calls).toBe(1);
    await gate.onLink("OK"); // backend came back
    expect(calls).toBe(2);
    expect(gate.loaded()).toBe(true);
  });
  it("loads only once: later OK pongs do nothing", async () => {
    let calls = 0;
    const gate = createSyncGate(async () => void calls++);
    await gate.attempt();
    await gate.onLink("OK");
    await gate.onLink("OK");
    expect(calls).toBe(1);
  });
  it("does not start a second load while one is in flight", async () => {
    let calls = 0;
    let release!: () => void;
    const gate = createSyncGate(() => new Promise<void>((r) => ((release = r), void calls++)));
    const first = gate.attempt();
    await gate.onLink("OK");
    expect(calls).toBe(1);
    release();
    await first;
    expect(gate.loaded()).toBe(true);
  });
});
