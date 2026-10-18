import { describe, expect, it } from "vitest";
import { countdown, depthBar, joinArg, ladder, parseCdepArgs, sPct, signClass, span, utc, type Level } from "./cryptoArgs";

describe("parseCdepArgs", () => {
  it("defaults to BTCUSDT and 25 levels", () => expect(parseCdepArgs([])).toEqual({ pair: "BTCUSDT", levels: 25 }));
  it("reads a pair and a level count in any order", () => {
    expect(parseCdepArgs(["50", "eth-usdt"])).toEqual({ pair: "ETH-USDT", levels: 50 });
    expect(parseCdepArgs(["BTC", "USDC"]).pair).toBe("BTCUSDC");
  });
  it("clamps the level count", () => {
    expect(parseCdepArgs(["2"]).levels).toBe(5);
    expect(parseCdepArgs(["999"]).levels).toBe(100);
  });
});

describe("table helpers", () => {
  it("joinArg trims and joins words", () => expect(joinArg(["", "arbitrum", "one"])).toBe("arbitrum one"));
  it("ladder pairs bids and asks best first and stops at n", () => {
    const b: Level[] = [[100, 1, 1, 100], [99, 1, 2, 199]];
    const a: Level[] = [[101, 2, 2, 202]];
    const rows = ladder(b, a, 5);
    expect(rows).toHaveLength(2);
    expect(rows[0].bid?.[0]).toBe(100);
    expect(rows[1].ask).toBeNull();
    expect(ladder(b, a, 1)).toHaveLength(1);
  });
  it("depthBar scales to the deeper side", () => {
    expect(depthBar(50, 100, 10)).toBe("#####");
    expect(depthBar(100, 100, 10)).toBe("##########");
    expect(depthBar(undefined, 100)).toBe("");
    expect(depthBar(1, 0)).toBe("");
  });
  it("sPct and signClass", () => {
    expect(sPct(1.234)).toBe("+1.23%");
    expect(sPct(-0.5, 1)).toBe("-0.5%");
    expect(sPct(null)).toBe("");
    expect(signClass(-1)).toBe("down");
    expect(signClass(0)).toBe("fg");
    expect(signClass(2)).toBe("up");
  });
  it("countdown and span", () => {
    expect(countdown(3_600_000 * 3 + 12 * 60_000, 0)).toBe("3H12M");
    expect(countdown(45 * 60_000, 0)).toBe("45M");
    expect(countdown(1, 2)).toBe("");
    expect(span(42)).toBe("42S");
    expect(span(720)).toBe("12M");
    expect(span(12600)).toBe("3.5H");
  });
  it("utc formats venue times", () => {
    expect(utc(0)).toBe("");
    expect(utc(Date.UTC(2026, 9, 18, 1, 2, 3))).toBe("2026-10-18 01:02:03");
  });
});
