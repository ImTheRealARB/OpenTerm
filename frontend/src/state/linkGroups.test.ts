// Phase 22: the link-group propagation rule (pure, no store).
import { describe, expect, it } from "vitest";
import { isLinkGroup, nextGroup, propagate } from "./linkGroups";
import type { PanelState, View } from "./workspace";

const sec = (symbol: string) => ({ symbol }) as View["security"];
const panel = (id: number, fn: string, symbol: string | undefined, link?: PanelState["link"]): PanelState => ({
  id,
  views: [{ fn, args: [], security: symbol ? sec(symbol) : undefined } as View],
  pos: 0,
  ...(link ? { link } : {}),
});
// In the app this comes from the registry; here: watchlists take no security, everything else does.
const uses = (v: View) => v.fn !== "WL";

describe("link groups", () => {
  it("cycles none, A, B, C, D, none", () => {
    expect(nextGroup(undefined)).toBe("A");
    expect(nextGroup("C")).toBe("D");
    expect(nextGroup("D")).toBeUndefined();
    expect(isLinkGroup("B")).toBe(true);
    expect(isLinkGroup("E")).toBe(false);
  });

  it("switches only same-group panels that take a security", () => {
    const panels = {
      1: panel(1, "GP", "MSFT", "A"),
      2: panel(2, "DES", "IBM", "A"),
      3: panel(3, "GP", "IBM", "B"),
      4: panel(4, "WL", undefined, "A"),
      5: panel(5, "GP", "IBM"),
    };
    const out = propagate(panels, 1, sec("MSFT"), uses);
    expect(out[2].views[0].security?.symbol).toBe("MSFT");
    expect(out[2].views).toHaveLength(1); // in place: no new history entry
    expect(out[3]).toBe(panels[3]); // other group
    expect(out[4]).toBe(panels[4]); // takes no security
    expect(out[5]).toBe(panels[5]); // no group
  });

  it("returns the same map when nothing changes", () => {
    const panels = { 1: panel(1, "GP", "MSFT"), 2: panel(2, "GP", "IBM", "A") };
    expect(propagate(panels, 1, sec("MSFT"), uses)).toBe(panels); // source has no group
    const same = { 1: panel(1, "GP", "MSFT", "A"), 2: panel(2, "GP", "MSFT", "A") };
    expect(propagate(same, 1, sec("MSFT"), uses)).toBe(same); // already on it
  });
});
