import { describe, expect, it } from "vitest";
import { parseWl } from "./watchlistArgs";

describe("parseWl", () => {
  it("views the index or one list", () => {
    expect(parseWl([])).toEqual({ kind: "view" });
    expect(parseWl(["tech"])).toEqual({ kind: "view", name: "TECH" });
  });

  it("adds and removes symbols, uppercased and deduplicated", () => {
    expect(parseWl(["tech", "add", "aapl", "msft", "AAPL"])).toEqual({ kind: "edit", name: "TECH", add: ["AAPL", "MSFT"], remove: [] });
    expect(parseWl(["TECH", "RM", "msft"])).toEqual({ kind: "edit", name: "TECH", add: [], remove: ["MSFT"] });
    expect(parseWl(["TECH", "DEL", "msft"])).toEqual({ kind: "edit", name: "TECH", add: [], remove: ["MSFT"] });
  });

  it("ADD with no symbols uses an explicitly typed security only", () => {
    expect(parseWl(["TECH", "ADD"], { symbol: "RELIANCE.NS", market: "IN" })).toEqual({ kind: "edit", name: "TECH", add: ["RELIANCE.NS"], remove: [] });
    expect(parseWl(["TECH", "ADD"])).toMatchObject({ kind: "error" });
  });

  it("deletes a whole list with WL DEL NAME", () => {
    expect(parseWl(["del", "tech"])).toEqual({ kind: "delete", name: "TECH" });
    expect(parseWl(["DEL"])).toMatchObject({ kind: "error", message: "WL DEL NEEDS A NAME" });
  });

  it("rejects bad names, bad symbols and unknown verbs", () => {
    expect(parseWl(["MY LIST"])).toMatchObject({ kind: "error" });
    expect(parseWl(["A".repeat(33)])).toMatchObject({ kind: "error" });
    expect(parseWl(["TECH", "ADD", "<b>"])).toMatchObject({ kind: "error", message: "BAD SYMBOL: <B>" });
    expect(parseWl(["TECH", "SORT"])).toMatchObject({ kind: "error" });
  });
});
