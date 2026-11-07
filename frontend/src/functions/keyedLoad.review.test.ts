import { describe, expect, it } from "vitest";
import { keyGate, latestOnly } from "./keyedLoad";

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

describe("keyGate (useEnvelope: an answer for an old key must not land after the key changed)", () => {
  it("an answer asked for the old key is dropped once the key changed", () => {
    const g = keyGate("AAPL");
    const askedFor = "AAPL";
    g.set("MSFT"); // the user typed a new symbol while the AAPL request was in flight
    expect(g.isCurrent(askedFor)).toBe(false);
    expect(g.isCurrent("MSFT")).toBe(true);
  });
  it("two answers for the same key both count (F5 or the auto refresh while one is still in flight)", () => {
    const g = keyGate("BTC-USD");
    expect(g.isCurrent("BTC-USD")).toBe(true);
    expect(g.isCurrent("BTC-USD")).toBe(true);
  });
  it("switching back to an earlier key makes its answers count again", () => {
    const g = keyGate("A");
    g.set("B");
    g.set("A");
    expect(g.isCurrent("A")).toBe(true);
  });
});
