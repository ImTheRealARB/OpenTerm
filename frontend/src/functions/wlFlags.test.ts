import { describe, expect, it } from "vitest";
import { applyMetaChange, buildRows, EMPTY_META, nextFilter, nextFlag } from "./wlFlags";

const id = (s: string) => s;

describe("watchlist flags and sections (Phase 22)", () => {
  it("cycles flags and filters only over colours in use", () => {
    expect(nextFlag(undefined)).toBe("RED");
    expect(nextFlag("GREY")).toBeUndefined();
    const meta = applyMetaChange(applyMetaChange(EMPTY_META, { kind: "flag", symbol: "A", color: "BLUE" }), { kind: "flag", symbol: "B", color: "RED" });
    expect(nextFilter(null, meta)).toBe("RED");
    expect(nextFilter("RED", meta)).toBe("BLUE");
    expect(nextFilter("BLUE", meta)).toBeNull();
    expect(applyMetaChange(meta, { kind: "flag", symbol: "A" }).flags).toEqual({ B: "RED" });
  });

  it("puts headers above their symbol in list order only, and filters by colour", () => {
    let meta = applyMetaChange(EMPTY_META, { kind: "section", before: "C", title: "Banks" });
    meta = applyMetaChange(meta, { kind: "flag", symbol: "C", color: "GREEN" });
    expect(buildRows(["A", "B", "C"], meta, id, null, true)).toEqual(["A", "B", { section: "Banks" }, "C"]);
    expect(buildRows(["C", "A"], meta, id, null, false)).toEqual(["C", "A"]); // sorted: no headers
    expect(buildRows(["A", "B", "C"], meta, id, "GREEN", true)).toEqual([{ section: "Banks" }, "C"]);
    expect(applyMetaChange(meta, { kind: "section", before: "C" }).sections).toEqual([]);
  });
});
