import { describe, expect, it } from "vitest";
import { moversAsOf } from "./moversAsOf";

// A time a few minutes ago, so fmtTime prints a clock time (older than 18 h it would print a date).
const recent = Math.floor(Date.now() / 1000) - 300;
const none = { table_as_of: {}, as_of_text: null, market_time: null };

describe("MOV header time", () => {
  it("shows the source's own sentence first (Nasdaq)", () => {
    const d = { ...none, table_as_of: { GAINERS: "Data as of 14:32 ET" }, as_of_text: "x", market_time: recent };
    expect(moversAsOf(d, "GAINERS", recent)).toBe("DATA AS OF 14:32 ET");
  });
  it("falls back to the newest quote time (Yahoo)", () => {
    expect(moversAsOf({ ...none, market_time: recent }, "GAINERS", recent)).toMatch(/^QUOTES \d\d:\d\d:\d\d$/);
  });
  it("says FETCHED when the source gave no time at all (TradingView), never a market time", () => {
    const d = { ...none, table_as_of: { GAINERS: null } };
    expect(moversAsOf(d, "GAINERS", recent)).toMatch(/^FETCHED \d\d:\d\d:\d\d$/);
  });
  it("shows nothing when there is no time to show", () => {
    expect(moversAsOf(none, "GAINERS", null)).toBeNull();
  });
});
