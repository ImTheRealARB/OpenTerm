import { describe, expect, it } from "vitest";
import { GROUP_CAP, defaultLimits, expand, groupSuggestions, moreLabel, sectorWord } from "./groupSuggestions";

const f = (v: string) => ({ value: v, label: v, kind: "FUNC" });
const s = (v: string, kind = "SEC") => ({ value: v, label: v, kind });
const nl = { value: "AAPL GP", label: "PRESS ENTER", kind: "NL" };

describe("groupSuggestions", () => {
  it("puts a header before each group, in the order the pipeline first produced them", () => {
    const g = groupSuggestions([s("AAPL"), s("MSFT", "RECENT"), f("GP"), f("DES")]);
    expect(g.rows.map((r) => (r.type === "header" ? r.label : r.type === "item" ? r.s.value : "more"))).toEqual([
      "SECURITIES", "AAPL", "MSFT", "FUNCTIONS", "GP", "DES",
    ]);
    const g2 = groupSuggestions([f("GP"), s("AAPL")]);
    expect(g2.rows[0]).toEqual({ type: "header", label: "FUNCTIONS" });
  });

  it("keeps NL / MEAN / ARG rows first and ungrouped (no header)", () => {
    const g = groupSuggestions([nl, f("GP"), s("AAPL")]);
    expect(g.rows[0]).toMatchObject({ type: "item", s: nl });
    expect(g.rows[1]).toEqual({ type: "header", label: "FUNCTIONS" });
    const only = groupSuggestions([{ value: "SRC=YAHOO", label: "", kind: "ARG" }]);
    expect(only.rows.some((r) => r.type === "header")).toBe(false);
  });

  it("never lets a header be selected: selectable skips headers and is numbered in screen order", () => {
    const g = groupSuggestions([f("GP"), f("DES"), s("AAPL")]);
    expect(g.selectable.every((r) => r.type === "item" || r.type === "more")).toBe(true);
    expect(g.selectable.map((r) => r.pos)).toEqual([0, 1, 2]);
    expect(g.selectable.map((r) => (r.type === "item" ? r.s.value : "more"))).toEqual(["GP", "DES", "AAPL"]);
  });

  it("caps a group and adds a More row that counts what is hidden", () => {
    const many = Array.from({ length: GROUP_CAP + 3 }, (_, i) => f("F" + i));
    const g = groupSuggestions(many);
    expect(g.selectable).toHaveLength(GROUP_CAP + 1);
    const last = g.selectable[g.selectable.length - 1];
    expect(last).toMatchObject({ type: "more", group: "FUNCTIONS", hidden: 3 });
  });

  it("shows no More row when everything fits (including exactly the cap)", () => {
    const g = groupSuggestions(Array.from({ length: GROUP_CAP }, (_, i) => f("F" + i)));
    expect(g.selectable.some((r) => r.type === "more")).toBe(false);
  });

  it("expand shows the next page; the position of More now holds the first new row", () => {
    const many = Array.from({ length: GROUP_CAP + 3 }, (_, i) => f("F" + i));
    const before = groupSuggestions(many).selectable;
    const morePos = before.length - 1;
    const after = groupSuggestions(many, expand(defaultLimits(), "FUNCTIONS")).selectable;
    expect(after).toHaveLength(GROUP_CAP + 3);
    expect(after.some((r) => r.type === "more")).toBe(false);
    expect(after[morePos]).toMatchObject({ type: "item", s: { value: "F" + GROUP_CAP } });
  });

  it("limits are per group", () => {
    const items = [...Array.from({ length: 6 }, (_, i) => f("F" + i)), ...Array.from({ length: 6 }, (_, i) => s("S" + i))];
    const g = groupSuggestions(items, expand(defaultLimits(), "SECURITIES"));
    const mores = g.selectable.filter((r) => r.type === "more");
    expect(mores).toHaveLength(1);
    expect(mores[0]).toMatchObject({ group: "FUNCTIONS" });
  });

  it("labels the More rows", () => {
    expect(moreLabel("FUNCTIONS")).toBe("More Functions...");
    expect(moreLabel("SECURITIES")).toBe("More Securities...");
  });
});

describe("sectorWord", () => {
  it("reads the symbol shape", () => {
    expect(sectorWord("^GSPC")).toBe("Index");
    expect(sectorWord("^TNX")).toBe("Govt");
    expect(sectorWord("EURUSD=X")).toBe("Curncy");
    expect(sectorWord("CL=F")).toBe("Comdty");
    expect(sectorWord("BTC-USD")).toBe("Crypto");
    expect(sectorWord("AAPL")).toBe("Equity");
    expect(sectorWord("RELIANCE.NS")).toBe("Equity");
    expect(sectorWord("BRK-B")).toBe("Equity"); // a share class, not a crypto pair
  });
  it("says nothing when it cannot tell", () => {
    expect(sectorWord("")).toBe("");
    expect(sectorWord("??")).toBe("");
  });
});
