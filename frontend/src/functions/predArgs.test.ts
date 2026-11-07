import { describe, expect, it } from "vitest";
import type { PredRow } from "../net/types";
import { PRED_LABEL, filterSrc, fmtOutcome, fmtPct, fmtProb, fmtVolume, parsePredArgs, predBars } from "./predArgs";

const row = (source: PredRow["source"], prob: number, outcome = "Yes"): PredRow => ({
  id: "1", source, question: "Q?", outcome, prob, pct: Math.round(prob * 1000) / 10, volume: 1, vol_unit: source === "polymarket" ? "USD" : "contracts",
  close: "2027-01-01", history: true, ref: "r", event: null,
});

describe("PRED arguments", () => {
  it("words become the filter, whitespace collapsed", () => {
    expect(parsePredArgs([])).toEqual({ q: "", src: "all", error: null });
    expect(parsePredArgs(["fed", "rate"])).toEqual({ q: "fed rate", src: "all", error: null });
    expect(parsePredArgs(["  fed   rate cut "])).toEqual({ q: "fed rate cut", src: "all", error: null });
  });
  it("SRC= keeps one source, case and position free", () => {
    expect(parsePredArgs(["bitcoin", "src=kalshi"])).toEqual({ q: "bitcoin", src: "kalshi", error: null });
    expect(parsePredArgs(["SRC=POLY", "iran"])).toEqual({ q: "iran", src: "polymarket", error: null });
    expect(parsePredArgs(["src=all"]).src).toBe("all");
  });
  it("a bad SRC says what is allowed and filters nothing", () => {
    const r = parsePredArgs(["x", "SRC=ftx"]);
    expect(r.error).toContain("SRC MUST BE POLY, KALSHI OR ALL");
    expect(r.q).toBe("");
    expect(parsePredArgs(["SRC="]).error).toContain("NOTHING");
  });
  it("the filter is capped at the server's 80 characters", () => {
    expect(parsePredArgs(["x".repeat(200)]).q).toHaveLength(80);
  });
});

describe("PRED text", () => {
  it("the label never changes", () => {
    expect(PRED_LABEL).toBe("MARKET-IMPLIED PROBABILITY, NOT A FORECAST");
  });
  it("probability shows as percent; a non-Yes lead outcome is named", () => {
    expect(fmtPct(0.145)).toBe("14.5%");
    expect(fmtPct(0)).toBe("0.0%");
    expect(fmtPct(null)).toBe("");
    expect(fmtProb(row("polymarket", 0.145))).toBe("14.5%");
    expect(fmtProb(row("polymarket", 0.41, "Lakers"))).toBe("41.0% LAKERS");
  });
  it("volume carries its unit: dollars for Polymarket, contracts for Kalshi", () => {
    expect(fmtVolume(74_580_410, "USD")).toBe("$74.6M");
    expect(fmtVolume(211_127, "contracts")).toBe("211.1K ct");
    expect(fmtVolume(950, "contracts")).toBe("950 ct");
    expect(fmtVolume(2.3e9, "USD")).toBe("$2.3B");
  });
  it("an outcome line shows the book only when the source has one", () => {
    expect(fmtOutcome({ name: "Yes", prob: 0.91, pct: 91, bid: 0.92, ask: 0.94 })).toContain("BID 92.0%  ASK 94.0%");
    expect(fmtOutcome({ name: "No", prob: 0.855, pct: 85.5, bid: null, ask: null })).not.toContain("BID");
    expect(fmtOutcome({ name: "Yes", prob: null, pct: null, bid: null, ask: null })).toContain("NO PRICE");
  });
  it("source filter", () => {
    const rows = [row("polymarket", 0.1), row("kalshi", 0.2)];
    expect(filterSrc(rows, "all")).toHaveLength(2);
    expect(filterSrc(rows, "kalshi").map((r) => r.source)).toEqual(["kalshi"]);
  });
});

describe("PRED chart series", () => {
  it("probabilities become a percent line", () => {
    const b = predBars({ source: "polymarket", id: "9", history: { t: [1, 2, 3], p: [0.1, 0.25, 0.2] } });
    expect(b).not.toBeNull();
    expect(Array.from(b!.c)).toEqual([10, 25, 20]);
    expect(b!.symbol).toBe("polymarket:9");
    expect(Array.from(b!.t)).toEqual([1, 2, 3]);
  });
  it("no history, one point, or ragged arrays chart nothing", () => {
    expect(predBars({ source: "kalshi", id: "x", history: null })).toBeNull();
    expect(predBars({ source: "kalshi", id: "x", history: { t: [1], p: [0.5] } })).toBeNull();
    expect(predBars({ source: "kalshi", id: "x", history: { t: [1, 2], p: [0.5] } })).toBeNull();
  });
});
