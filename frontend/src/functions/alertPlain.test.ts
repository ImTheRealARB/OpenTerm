import { describe, expect, it } from "vitest";
import { plainAlert } from "./alertPlain";

const base = { id: 1, status: "active" as const, created_at: 0, triggered_at: null, trigger_price: null, channels: null };
describe("plainAlert", () => {
  it("reads a price alert as a sentence", () => {
    expect(plainAlert({ ...base, symbol: "AAPL", op: ">", unit: "price", value: 200 }, null)).toBe("Alert when AAPL goes above 200");
    expect(plainAlert({ ...base, symbol: "AAPL", op: "<", unit: "price", value: 150 }, null)).toBe("Alert when AAPL goes below 150");
  });
  it("reads a percent alert", () => {
    expect(plainAlert({ ...base, symbol: "TSLA", op: "<", unit: "pct", value: -3 }, null)).toBe("Alert when TSLA moves down more than 3% in a day");
  });
  it("reads a news alert", () => {
    const n = { id: 2, word: "recall", symbol: "AAPL", status: "active" as const, created_at: 0, triggered_at: null, headline: null, url: null, channels: null };
    expect(plainAlert(null, n)).toBe('Alert when news mentions "recall" for AAPL');
    expect(plainAlert(null, { ...n, symbol: null })).toMatch(/top stories/);
  });
});
