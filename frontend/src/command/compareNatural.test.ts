import { describe, expect, it } from "vitest";
import { parseGpArgs } from "../functions/gpArgs";
import { compareCommand, parseCompare, rangeFrom } from "./compareNatural";

const NAMES: Record<string, string> = {
  apple: "AAPL", microsoft: "MSFT", tesla: "TSLA", ford: "F", aapl: "AAPL", msft: "MSFT", google: "GOOGL", amazon: "AMZN",
  "johnson and johnson": "JNJ", pfizer: "PFE", "3m": "MMM", nvidia: "NVDA",
};
const resolve = (p: string) => NAMES[p] ?? null;
const cmd = (t: string) => compareCommand(t, resolve).command;

describe("parseCompare", () => {
  const cases: [string, string, string, string | undefined][] = [
    ["apple vs microsoft 1 year", "apple", "microsoft", "1Y"],
    ["compare tesla and ford", "tesla", "ford", undefined],
    ["aapl versus msft 5y", "aapl", "msft", "5Y"],
    ["Apple vs. Microsoft", "apple", "microsoft", undefined],
    ["tesla against ford over the last 6 months", "tesla", "ford", "6M"],
    ["compare apple with microsoft for 2 years", "apple", "microsoft", "2Y"],
    ["compare apple and microsoft ytd", "apple", "microsoft", "YTD"],
    ["apple compared to microsoft past 10 years", "apple", "microsoft", "10Y"],
    ["show me apple vs microsoft stock performance this year", "apple", "microsoft", "YTD"],
    ["chart tesla vs ford max", "tesla", "ford", "MAX"],
    ["apple v microsoft 3 months", "apple", "microsoft", "3M"],
    ["apple vs microsoft 1 week", "apple", "microsoft", "5D"],
    ["compare apple and microsoft over the last 5 days", "apple", "microsoft", "5D"],
    ["how does tesla compare vs ford", "how does tesla compare", "ford", undefined],
    ["compare johnson and johnson vs pfizer", "johnson and johnson", "pfizer", undefined],
    ["apple vs 3m", "apple", "3m", undefined],
  ];
  for (const [text, a, b, range] of cases) {
    it(text, () => {
      const p = parseCompare(text);
      expect(p?.a).toBe(a);
      expect(p?.b).toBe(b);
      expect(p?.range).toBe(range);
    });
  }
  it("three-way compare", () => {
    const p = parseCompare("apple vs microsoft vs google 1y")!;
    expect([p.a, p.b, ...p.more]).toEqual(["apple", "microsoft", "google"]);
  });
  it("a range GP has no button for is reported, not guessed", () => {
    const p = parseCompare("apple vs microsoft 3 years")!;
    expect(p.range).toBeUndefined();
    expect(p.badRange).toBe("3 YEARS");
  });
  it("not a comparison", () => {
    expect(parseCompare("apple")).toBeNull();
    expect(parseCompare("compare apple")).toBeNull();
    expect(parseCompare("")).toBeNull();
  });
});

describe("compareCommand", () => {
  it("builds the GP compare command", () => {
    expect(cmd("apple vs microsoft 1 year")).toBe("AAPL GP 1Y VS MSFT");
    expect(cmd("compare tesla and ford")).toBe("TSLA GP VS F");
    expect(cmd("aapl versus msft 5y")).toBe("AAPL GP 5Y VS MSFT");
    expect(cmd("apple vs microsoft vs google ytd")).toBe("AAPL GP YTD VS MSFT GOOGL");
  });
  it("the command is understood by the GP parser", () => {
    const c = cmd("apple vs microsoft vs amazon 5 years")!;
    const [, , ...args] = c.split(" ");
    const gp = parseGpArgs(args);
    expect(gp.range).toBe("5Y");
    expect(gp.compare).toEqual(["MSFT", "AMZN"]);
  });
  it("unknown company is an error naming it", () => {
    const r = compareCommand("apple vs zorp", resolve);
    expect(r.command).toBeUndefined();
    expect(r.error).toBe("UNKNOWN COMPANY: ZORP");
  });
  it("same security twice is an error", () => {
    expect(compareCommand("apple vs aapl", resolve).error).toContain("SAME");
  });
  it("needs two names", () => {
    expect(compareCommand("apple", resolve).error).toContain("TWO NAMES");
  });
});

describe("rangeFrom", () => {
  it("maps units", () => {
    expect(rangeFrom(1, "year")).toBe("1Y");
    expect(rangeFrom(6, "months")).toBe("6M");
    expect(rangeFrom(5, "days")).toBe("5D");
    expect(rangeFrom(null, "ytd")).toBe("YTD");
    expect(rangeFrom(2, "fortnights")).toBeNull();
  });
});
