import { describe, expect, it } from "vitest";
import { fallbackText, rowsFallbackText } from "./fallbackText";

describe("fallbackText", () => {
  it("says the reason when the backend gave one", () => {
    expect(fallbackText(["kite"], { kite: "KITE LOGIN EXPIRED: run KITE LOGIN" })).toBe("KITE LOGIN EXPIRED: RUN KITE LOGIN, VIA FALLBACK");
  });
  it("keeps the generic text for sources without a reason", () => {
    expect(fallbackText(["yahoo", "nasdaq"])).toBe("YAHOO,NASDAQ DOWN, VIA FALLBACK");
  });
  it("mixes both", () => {
    expect(fallbackText(["kite", "yahoo"], { kite: "KITE LOGIN EXPIRED" })).toBe("KITE LOGIN EXPIRED, VIA FALLBACK · YAHOO DOWN, VIA FALLBACK");
  });
  it("is empty for no fallback", () => {
    expect(fallbackText([])).toBe("");
  });
  it("merges the rows of a quote table into one line", () => {
    const rows = [
      { fallbackFrom: ["kite"], fallbackNotes: { kite: "KITE LOGIN EXPIRED: run KITE LOGIN" } },
      { fallbackFrom: ["kite"], fallbackNotes: { kite: "KITE LOGIN EXPIRED: run KITE LOGIN" } },
      {},
    ];
    expect(rowsFallbackText(rows)).toBe("KITE LOGIN EXPIRED: RUN KITE LOGIN, VIA FALLBACK");
    expect(rowsFallbackText([{}, {}])).toBe("");
  });
});
