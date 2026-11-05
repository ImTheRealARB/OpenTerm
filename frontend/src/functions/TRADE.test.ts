import { describe, expect, it } from "vitest";
import { FUNCTIONS } from "./registry";

// Registry check. The argument and number logic is tested in usArgs.test.ts (pure code); the panel itself needs a key and a backend.
describe("TRADE registry entry", () => {
  it("is registered with a loader", () => {
    const def = FUNCTIONS.get("TRADE");
    expect(def).toBeDefined();
    expect(def?.load).toBeTypeOf("function");
  });
});
