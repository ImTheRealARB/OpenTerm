import { describe, expect, it } from "vitest";
import { FUNCTIONS } from "./registry";

// Stub scaffolded by scripts/new_function.py. Put pure parsing/formatting logic in its own file and test it here.
describe("GF registry entry", () => {
  it("is registered with a loader", () => {
    const def = FUNCTIONS.get("GF");
    expect(def).toBeDefined();
    expect(def?.load).toBeTypeOf("function");
  });
});
