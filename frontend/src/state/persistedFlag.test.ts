import { afterEach, describe, expect, it, vi } from "vitest";
import { persistedFlag } from "./persistedFlag";

/** A tiny localStorage stand-in (vitest runs in Node, which has none). `broken` makes every access throw, like a blocked browser. */
function stubStorage(initial: Record<string, string> = {}, broken = false) {
  const data = new Map(Object.entries(initial));
  vi.stubGlobal("localStorage", {
    getItem: (k: string) => {
      if (broken) throw new Error("blocked");
      return data.get(k) ?? null;
    },
    setItem: (k: string, v: string) => {
      if (broken) throw new Error("blocked");
      data.set(k, v);
    },
  });
  return data;
}

afterEach(() => vi.unstubAllGlobals());

describe("persistedFlag", () => {
  it("starts at the default when nothing, or something other than 1 / 0, is stored", () => {
    stubStorage({ junk: "maybe" });
    expect(persistedFlag("unset", true).get()).toBe(true);
    expect(persistedFlag("unset", false).get()).toBe(false);
    expect(persistedFlag("junk", true).get()).toBe(true);
    expect(persistedFlag("junk", false).get()).toBe(false);
  });

  it("reads an earlier 1 / 0, whatever the default", () => {
    stubStorage({ k1: "1", k0: "0" });
    expect(persistedFlag("k1", false).get()).toBe(true);
    expect(persistedFlag("k0", true).get()).toBe(false);
  });

  it("writes every change back as 1 / 0", () => {
    const data = stubStorage();
    const f = persistedFlag("k", false);
    f.toggle();
    expect(f.get()).toBe(true);
    expect(data.get("k")).toBe("1");
    f.set(false);
    expect(data.get("k")).toBe("0");
  });

  it("keeps working for this page load when storage is blocked", () => {
    stubStorage({}, true);
    const f = persistedFlag("k", true);
    expect(f.get()).toBe(true);
    f.toggle();
    expect(f.get()).toBe(false);
  });

  it("works without any storage at all (Node)", () => {
    const f = persistedFlag("k", true);
    f.toggle();
    expect(f.get()).toBe(false);
  });
});
