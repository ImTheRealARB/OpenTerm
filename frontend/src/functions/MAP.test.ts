import { describe, expect, it } from "vitest";
import { FUNCTIONS } from "./registry";

// Stub scaffolded by scripts/new_function.py. Put pure parsing/formatting logic in its own file and test it here.
describe("MAP registry entry", () => {
  it("is registered with a loader", () => {
    const def = FUNCTIONS.get("MAP");
    expect(def).toBeDefined();
    expect(def?.load).toBeTypeOf("function");
  });
});
