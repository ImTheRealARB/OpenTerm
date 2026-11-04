import { describe, expect, it } from "vitest";
import { alertDirection, alertTick, fmtAlertPrice, roundAlertPrice } from "./alertPrice";

describe("alertPrice", () => {
  it("ticks by magnitude", () => {
    expect(alertTick(0.05)).toBe(0.0001);
    expect(alertTick(0.5)).toBe(0.001);
    expect(alertTick(5)).toBe(0.01);
    expect(alertTick(231)).toBe(0.05);
    expect(alertTick(2500)).toBe(0.5);
    expect(alertTick(50000)).toBe(1);
  });
  it("rounds and formats", () => {
    expect(roundAlertPrice(231.4937)).toBe(231.5);
    expect(fmtAlertPrice(231.5)).toBe("231.50");
    expect(roundAlertPrice(4.3271)).toBe(4.33);
    expect(roundAlertPrice(0.4567)).toBe(0.457);
    expect(fmtAlertPrice(0.457)).toBe("0.457");
    expect(roundAlertPrice(64321.7)).toBe(64322);
    expect(fmtAlertPrice(64322)).toBe("64322");
    expect(roundAlertPrice(2503.3)).toBe(2503.5);
  });
  it("rejects non-prices", () => {
    expect(roundAlertPrice(NaN)).toBeNull();
    expect(roundAlertPrice(-3)).toBeNull();
    expect(roundAlertPrice(0)).toBeNull();
  });
  it("picks the direction from the last price", () => {
    expect(alertDirection(231.5, 220)).toBe(">");
    expect(alertDirection(200, 220)).toBe("<");
    expect(alertDirection(220, 220)).toBe(">");
  });
});
