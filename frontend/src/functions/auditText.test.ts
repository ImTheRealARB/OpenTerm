import { describe, expect, it } from "vitest";
import { purgeMessage, purgeStep } from "./auditText";

describe("AUDIT purge step", () => {
  it("asks first, runs on the same key again", () => {
    expect(purgeStep(null, "p")).toEqual({ ask: "ONE", run: null });
    expect(purgeStep("ONE", "P")).toEqual({ ask: null, run: "ONE" });
    expect(purgeStep(null, "x")).toEqual({ ask: "ALL", run: null });
    expect(purgeStep("ALL", "x")).toEqual({ ask: null, run: "ALL" });
  });
  it("the other purge key switches the question instead of running", () => {
    expect(purgeStep("ONE", "x")).toEqual({ ask: "ALL", run: null });
  });
  it("any other key cancels", () => {
    expect(purgeStep("ALL", "j")).toEqual({ ask: null, run: null });
  });
  it("words the result with the chain verdict", () => {
    expect(purgeMessage("ONE", 7, 1, true)).toBe("STORED TEXT OF ENTRY 7 REMOVED · CHAIN STILL VERIFIES (TEXT IS OUTSIDE THE HASH)");
    expect(purgeMessage("ALL", 0, 3, true)).toContain("3 ENTRIES");
    expect(purgeMessage("ALL", 0, 0, null)).toBe("NO STORED TEXT TO REMOVE");
    expect(purgeMessage("ONE", 1, 1, false)).toContain("CHAIN BROKEN");
  });
});
