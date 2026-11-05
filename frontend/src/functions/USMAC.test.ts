import { describe, expect, it } from "vitest";
import { FUNCTIONS } from "./registry";

// Registry check. The argument and number logic is tested in usArgs.test.ts (pure code); the panel itself needs a key and a backend.
describe("USMAC registry entry", () => {
  it("is registered with a loader", () => {
    const def = FUNCTIONS.get("USMAC");
    expect(def).toBeDefined();
    expect(def?.load).toBeTypeOf("function");
  });
});
