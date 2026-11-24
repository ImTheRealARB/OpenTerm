import { describe, expect, it } from "vitest";
import { parseLiveArgs } from "./liveArgs";
import { firstValues, parseOptArgs, renderRule } from "./optArgs";
import { parseBtArgs } from "./ruleParse";

describe("BT OPT arguments (Phase 26)", () => {
  it("builds the request from a rule with ranges and options", () => {
    const r = parseOptArgs(["AAPL", "SMA{10..50:5}>SMA{50..200:25}", "1D", "10Y", "METHOD=GA", "POP=20", "GEN=5", "WF=4", "ANCHORED", "STOP=5", "FILL=INTRABAR"]);
    expect(r.ok && r.req).toMatchObject({ symbols: ["AAPL"], rule: "SMA{10..50:5}>SMA{50..200:25}", range: "10Y", method: "GA", pop: 20, gen: 5, wf: 4,
      anchored: true, options: { stop_pct: 5, fill: "intrabar" } });
  });

  it("refuses a rule without ranges, a bad rule and loose words", () => {
    expect(parseOptArgs(["AAPL", "SMA20>SMA50"]).ok).toBe(false);
    expect(parseOptArgs(["AAPL", "SMA{10..50}>>SMA50"]).ok).toBe(false);
    expect(parseOptArgs(["AAPL", "SMA{10..50}>SMA200", "METHOD=SA"]).ok).toBe(false);
    expect(parseOptArgs(["AAPL", "SMA{10..50}>SMA200", "FILL=INTRABAR"]).ok).toBe(false); // FILL needs STOP or TARGET
  });

  it("takes a saved Python strategy with named ranges", () => {
    const r = parseOptArgs(["AAPL", "@mine", "FAST={10..30:10}", "SLOW={50..100:50}"]);
    expect(r.ok && r.req).toMatchObject({ strategy: "mine", ranges: { FAST: "{10..30:10}", SLOW: "{50..100:50}" } });
    expect(parseOptArgs(["AAPL", "@mine"]).ok).toBe(false);
  });

  it("renders a run's rule and the first values", () => {
    expect(firstValues("SMA{10..50:5}>SMA{50..200:25}")).toBe("SMA10>SMA50");
    expect(renderRule("SMA{10..50:5}>SMA{50..200:25}", ["15", "100"])).toBe("SMA15>SMA100");
  });
});

describe("BT exits and BT LIVE (Phase 26)", () => {
  it("parses STOP= TARGET= on a normal run", () => {
    const r = parseBtArgs(["AAPL", "SMA20>SMA50", "STOP=5%", "TARGET=12"]);
    expect(r.ok && r.sub === undefined && [r.stop, r.target]).toEqual([5, 12]);
  });

  it("parses the forward-test commands", () => {
    expect(parseLiveArgs([])).toEqual({ ok: true, act: "list" });
    expect(parseLiveArgs(["AAPL", "@mine", "1W", "CASH=5000"])).toEqual({ ok: true, act: "start", symbol: "AAPL", strategy: "mine", interval: "1W", cash: 5000 });
    expect(parseLiveArgs(["STOP", "0a1b2c3d"])).toEqual({ ok: true, act: "stop", id: "0a1b2c3d" });
    expect(parseLiveArgs(["AAPL"]).ok).toBe(false);
  });
});
