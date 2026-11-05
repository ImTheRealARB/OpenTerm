import { describe, expect, it } from "vitest";
import { addrQuery, agoText, fmtCoin, fmtGwei, shortHex, txTime } from "./addrArgs";
import { FUNCTIONS } from "./registry";

describe("ADDR registry entry", () => {
  it("is registered with a loader and no security", () => {
    const def = FUNCTIONS.get("ADDR");
    expect(def).toBeDefined();
    expect(def?.load).toBeTypeOf("function");
    expect(def?.needsSecurity).toBe(false);
  });
});

describe("ADDR helpers", () => {
  it("shows the gas price when no words are given", () => {
    expect(addrQuery([])).toBe("GAS");
    expect(addrQuery(["0xabc", "ARB"])).toBe("0xabc ARB");
  });

  it("shortens long hex values and leaves short ones alone", () => {
    const h = "0xf9db905d77704596d3600816bc70201586cfeec13bcf576320e2f38d6ca851a0";
    expect(shortHex(h)).toBe("0xf9db90...a851a0");
    expect(shortHex("0x12")).toBe("0x12");
    expect(shortHex(null)).toBe("");
  });

  it("formats amounts with fewer decimals as they grow, and keeps zero as 0", () => {
    expect(fmtCoin(0)).toBe("0");
    expect(fmtCoin(0.000123456789)).toBe("0.000123");
    expect(fmtCoin(12.3456789)).toBe("12.3457");
    expect(fmtCoin(172774.397764)).toBe("172,774.4");
    expect(fmtCoin(null)).toBe("");
  });

  it("formats gwei with enough decimals for sub-1 prices", () => {
    expect(fmtGwei(0.496839934)).toBe("0.4968");
    expect(fmtGwei(1.234)).toBe("1.23");
    expect(fmtGwei(35.67)).toBe("35.7");
    expect(fmtGwei(null)).toBe("");
  });

  it("gives an age and a UTC time", () => {
    expect(agoText(1000, 1030)).toBe("30S");
    expect(agoText(1000, 1000 + 600)).toBe("10M");
    expect(agoText(1000, 1000 + 7200)).toBe("2H");
    expect(agoText(1000, 1000 + 86400 * 3)).toBe("3D");
    expect(agoText(null, 5)).toBe("");
    expect(txTime(1759129619)).toBe("2025-09-29 07:06");
    expect(txTime(null)).toBe("");
  });
});
