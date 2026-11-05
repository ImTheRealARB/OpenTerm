import { describe, expect, it } from "vitest";
import { FUNCTIONS } from "./registry";
import { dueText, readable, statusClass, ukcoQuery, yesNo } from "./ukcoArgs";

describe("UKCO registry entry", () => {
  it("is registered with a loader and no security", () => {
    const def = FUNCTIONS.get("UKCO");
    expect(def).toBeDefined();
    expect(def?.load).toBeTypeOf("function");
    expect(def?.needsSecurity).toBe(false);
  });
});

describe("UKCO helpers", () => {
  it("joins every word after the code into one query", () => {
    expect(ukcoQuery(["tesco", "plc"])).toBe("tesco plc");
    expect(ukcoQuery(["00445790"])).toBe("00445790");
    expect(ukcoQuery([])).toBe("");
    expect(ukcoQuery(["", " "])).toBe("");
  });

  it("flags an overdue date and leaves a missing one empty", () => {
    expect(dueText("2026-12-31", false)).toBe("2026-12-31");
    expect(dueText("2026-12-31", true)).toBe("2026-12-31 OVERDUE");
    expect(dueText(null, true)).toBe("");
  });

  it("says NOT GIVEN for a missing flag instead of NO", () => {
    expect(yesNo(true)).toBe("YES");
    expect(yesNo(false)).toBe("NO");
    expect(yesNo(null)).toBe("NOT GIVEN");
    expect(yesNo(undefined)).toBe("NOT GIVEN");
  });

  it("only an active company is plain; anything else is a warning", () => {
    expect(statusClass("active")).toBe("fg");
    expect(statusClass("dissolved")).toBe("warn");
    expect(statusClass("liquidation")).toBe("warn");
    expect(statusClass(null)).toBe("fg");
  });

  it("makes register codes readable", () => {
    expect(readable("england-wales")).toBe("ENGLAND WALES");
    expect(readable(null)).toBe("");
  });
});
