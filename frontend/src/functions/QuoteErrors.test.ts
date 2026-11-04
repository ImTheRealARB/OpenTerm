import { describe, expect, it } from "vitest";
import { quoteErrorSummary } from "./QuoteErrors";

describe("quoteErrorSummary", () => {
  it("is null when every row loaded", () => {
    expect(quoteErrorSummary([{ symbol: "AAPL" }])).toBeNull();
  });
  it("says provider down with a count and keeps the exact text", () => {
    const s = quoteErrorSummary([{ symbol: "A", error: "PROVIDER DOWN" }, { symbol: "B" }, { symbol: "C", error: "PROVIDER DOWN" }])!;
    expect(s.text).toBe("ERR: PROVIDER DOWN (2 of 3: A, C)");
    expect(s.plain).toMatch(/isn't answering for 2 names/);
  });
  it("tells a missing quote apart from an outage", () => {
    expect(quoteErrorSummary([{ symbol: "NVDA", error: "NO DATA FOR SYMBOL" }])!.plain).toMatch(/no quote for 1 name\./);
  });
});
