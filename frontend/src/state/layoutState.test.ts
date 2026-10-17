import { describe, expect, it } from "vitest";
import { LAYOUT_NAME_RE, parseLayout, snapshot } from "./layoutState";
import type { WorkspaceState } from "./workspace";

const known = (c: string) => ["GP", "Q", "DES", "HELP"].includes(c);

const ws: WorkspaceState = {
  layout: { t: "split", dir: "v", ratio: 0.3, a: { t: "leaf", id: 1 }, b: { t: "leaf", id: 4 } },
  panels: {
    1: { id: 1, views: [{ fn: "HELP", args: [] }, { fn: "GP", security: { symbol: "AAPL" }, args: ["1Y"] }], pos: 1 },
    4: { id: 4, views: [{ fn: "Q", args: ["AAPL", "MSFT"] }], pos: 0 },
  },
  focus: 4,
  maximized: null,
  name: "DESK",
};

describe("snapshot", () => {
  it("keeps only the current view of each panel and drops the name", () => {
    const s = snapshot(ws);
    expect(s.panels[1]).toEqual({ id: 1, views: [{ fn: "GP", security: { symbol: "AAPL" }, args: ["1Y"] }], pos: 0 });
    expect("name" in s).toBe(false);
    expect(s.layout).toBe(ws.layout);
  });
});

describe("parseLayout", () => {
  it("round-trips a snapshot", () => {
    const s = JSON.parse(JSON.stringify(snapshot(ws)));
    expect(parseLayout(s, known)).toEqual(snapshot(ws));
  });

  it("rejects broken trees", () => {
    expect(parseLayout(null, known)).toBeNull();
    expect(parseLayout({ layout: { t: "leaf", id: 0 }, panels: {} }, known)).toBeNull();
    expect(parseLayout({ layout: { t: "leaf", id: 10 }, panels: {} }, known)).toBeNull();
    const dup = { t: "split", dir: "v", ratio: 0.5, a: { t: "leaf", id: 1 }, b: { t: "leaf", id: 1 } };
    expect(parseLayout({ layout: dup, panels: {} }, known)).toBeNull();
    expect(parseLayout({ layout: { t: "split", dir: "x", a: {}, b: {} }, panels: {} }, known)).toBeNull();
  });

  it("repairs what it can: unknown functions, bad focus, ratio, missing panels", () => {
    const raw = {
      layout: { t: "split", dir: "h", ratio: 5, a: { t: "leaf", id: 2 }, b: { t: "leaf", id: 3 } },
      panels: { 2: { views: [{ fn: "NOPE", security: { symbol: "MSFT" }, args: ["X", 1] }], pos: 0 }, 9: {} },
      focus: 9,
      maximized: 3,
    };
    const s = parseLayout(raw, known)!;
    expect(s.layout).toEqual({ t: "split", dir: "h", ratio: 0.9, a: { t: "leaf", id: 2 }, b: { t: "leaf", id: 3 } });
    expect(s.panels[2].views[0]).toEqual({ security: { symbol: "MSFT" }, args: ["X"] });
    expect(s.panels[3].views[0]).toEqual({ args: [] });
    expect(Object.keys(s.panels)).toEqual(["2", "3"]);
    expect(s.focus).toBe(2);
    expect(s.maximized).toBe(3);
  });
});

describe("layout names", () => {
  it("matches the backend rule", () => {
    expect(LAYOUT_NAME_RE.test("DESK-1")).toBe(true);
    expect(LAYOUT_NAME_RE.test("A".repeat(32))).toBe(true);
    expect(LAYOUT_NAME_RE.test("A".repeat(33))).toBe(false);
    expect(LAYOUT_NAME_RE.test("-X")).toBe(false);
    expect(LAYOUT_NAME_RE.test("my desk")).toBe(false);
  });
});
