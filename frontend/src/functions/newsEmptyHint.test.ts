import { describe, expect, it } from "vitest";
import { newsEmptyHint } from "./newsArgs";

// The empty-state hint must name the next thing to try, and mention the query so the user sees what came back empty.
describe("newsEmptyHint", () => {
  it("names the symbol and offers a keyword search", () => {
    const h = newsEmptyHint({ kind: "symbol", symbol: "AAPL" });
    expect(h).toContain("AAPL");
    expect(h).toContain("N <words>");
  });
  it("names the keywords and offers broader words", () => {
    const h = newsEmptyHint({ kind: "keyword", q: "RATE CUT" });
    expect(h).toContain("RATE CUT");
    expect(h).toContain("broader");
  });
  it("tells the top-stories view to retry", () => {
    expect(newsEmptyHint({ kind: "top" })).toContain("F5");
  });
});
