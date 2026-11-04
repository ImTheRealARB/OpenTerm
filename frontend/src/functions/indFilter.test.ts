import { describe, expect, it } from "vitest";
import { filterIndicators, parseQuery } from "./indFilter";

const rows = [
  { id: "SMA", name: "Simple moving average", category: "trend", plain: "The average close of the last N bars." },
  { id: "RSI", name: "Relative Strength Index", category: "momentum", plain: "Scores recent gains against losses." },
  { id: "STOCHRSI", name: "Stochastic RSI", category: "momentum", plain: "The stochastic formula applied to RSI." },
  { id: "OBV", name: "On-balance volume", category: "volume", plain: "A running total of volume." },
];

describe("indicator search", () => {
  it("exact id first, then prefix, then name", () => {
    expect(filterIndicators(rows, "rsi").map((r) => r.id)).toEqual(["RSI", "STOCHRSI"]);
    expect(filterIndicators(rows, "relative").map((r) => r.id)).toEqual(["RSI"]);
  });
  it("matches category and plain text, all words must match", () => {
    expect(filterIndicators(rows, "volume").map((r) => r.id)).toEqual(["OBV"]);
    expect(filterIndicators(rows, "moving average").map((r) => r.id)).toEqual(["SMA"]);
    expect(filterIndicators(rows, "rsi volume")).toEqual([]);
  });
  it("empty query keeps catalog order; numbers become params", () => {
    expect(filterIndicators(rows, "  ")).toBe(rows);
    expect(parseQuery("rsi 21")).toEqual({ words: ["rsi"], params: [21] });
    expect(parseQuery("macd(12,26,9)")).toEqual({ words: ["macd"], params: [12, 26, 9] });
    expect(filterIndicators(rows, "rsi 21").map((r) => r.id)[0]).toBe("RSI");
  });
});
