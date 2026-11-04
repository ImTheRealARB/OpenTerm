import { describe, expect, it } from "vitest";
import { idlePreload } from "./idlePreload";

describe("idlePreload", () => {
  it("loads every code, a few per idle slot", async () => {
    const loaded: string[] = [];
    let slots = 0;
    const queue: (() => void)[] = [];
    idlePreload(
      ["A", "B", "C", "D", "E"],
      async (c) => {
        loaded.push(c);
        if (c === "B") throw new Error("chunk failed"); // must not stop the rest
      },
      (cb) => {
        slots++;
        queue.push(cb);
      },
      2,
    );
    while (queue.length) {
      queue.shift()!();
      await new Promise((r) => setTimeout(r, 0));
    }
    expect(loaded).toEqual(["A", "B", "C", "D", "E"]);
    expect(slots).toBe(3);
  });
  it("does nothing for an empty list", () => {
    let called = false;
    idlePreload([], async () => {}, () => (called = true));
    expect(called).toBe(false);
  });
});
