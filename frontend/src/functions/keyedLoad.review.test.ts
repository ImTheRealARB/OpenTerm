import { describe, expect, it } from "vitest";
import { latestOnly } from "./keyedLoad";

describe("latestOnly (COMP: a slow answer for the old symbol must not overwrite the new one)", () => {
  it("only the most recent start is current", () => {
    const g = latestOnly();
    const a = g.start();
    const b = g.start();
    expect(a()).toBe(false);
    expect(b()).toBe(true);
  });
  it("invalidate makes every pending call stale (unmount)", () => {
    const g = latestOnly();
    const a = g.start();
    g.invalidate();
    expect(a()).toBe(false);
  });
  it("simulated race: the slow first request is dropped", async () => {
    const g = latestOnly();
    let shown = "";
    const run = async (sym: string, ms: number) => {
      const ok = g.start();
      await new Promise((r) => setTimeout(r, ms));
      if (ok()) shown = sym;
    };
    await Promise.all([run("OLD", 30), run("NEW", 5)]);
    expect(shown).toBe("NEW");
  });
});
