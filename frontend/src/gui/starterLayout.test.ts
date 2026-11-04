import { describe, expect, it } from "vitest";
import { FUNCTIONS } from "../functions/registry";
import { starterWorkspace } from "./starterLayout";

describe("starter layout for a new GUI user", () => {
  const ws = starterWorkspace();

  it("has three panels, all built functions, focus on panel 1", () => {
    expect(Object.keys(ws.panels)).toEqual(["1", "2", "3"]);
    for (const p of Object.values(ws.panels)) expect(FUNCTIONS.get(p.views[0].fn!)?.load, p.views[0].fn).toBeTypeOf("function");
    expect(ws.focus).toBe(1);
  });

  it("shows only real-data functions (no synthetic or fixture symbols)", () => {
    const syms = Object.values(ws.panels).flatMap((p) => [...p.views[0].args, p.views[0].security?.symbol ?? ""]);
    expect(syms.some((s) => s.startsWith("SYN"))).toBe(false);
  });
});
