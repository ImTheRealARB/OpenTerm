import { describe, expect, it } from "vitest";
import type { WorkspaceState } from "../state/workspace";
import { homeWorkspace, openHomeOnStart, shouldOpenHome } from "./startup";

// A tiny in-memory stand-in for sessionStorage.
const mem = () => {
  const m = new Map<string, string>();
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v) };
};

describe("start-up", () => {
  it("opens HOME only for startup=home and only once per session", () => {
    expect(shouldOpenHome("home", false)).toBe(true);
    expect(shouldOpenHome("home", true)).toBe(false);
    expect(shouldOpenHome("layout", false)).toBe(false);
  });

  it("replaces the workspace on the first call and leaves a reload alone", () => {
    const store = mem();
    let applied: WorkspaceState | null = null;
    expect(openHomeOnStart("home", (w) => (applied = w), store)).toBe(true);
    expect(applied).toEqual(homeWorkspace());
    expect(applied!.panels[1].views[0].fn).toBe("HOME");
    applied = null;
    expect(openHomeOnStart("home", (w) => (applied = w), store)).toBe(false); // same session (a reload)
    expect(applied).toBeNull();
  });

  it("startup=layout never touches the workspace; no storage means no change", () => {
    let called = 0;
    expect(openHomeOnStart("layout", () => void called++, mem())).toBe(false);
    expect(openHomeOnStart("home", () => void called++, null)).toBe(false);
    expect(called).toBe(0);
  });
});
