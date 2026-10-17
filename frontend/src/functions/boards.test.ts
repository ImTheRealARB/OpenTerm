import { describe, expect, it } from "vitest";
import { fmtRate } from "../format";
import { BOARDS, FXC_DEFAULT, crossPair, crossRate, parseCurrencies, usdLeg } from "./boards";
import { newsQuery } from "./newsArgs";

describe("boards", () => {
  it("every board lists each symbol once, in Yahoo form", () => {
    for (const b of Object.values(BOARDS)) {
      const syms = b.sections.flatMap((s) => s.items.map((i) => i.symbol));
      expect(new Set(syms).size, b.code).toBe(syms.length);
      for (const s of syms) expect(s, b.code).toMatch(/^[A-Z0-9^][A-Z0-9^=.-]*$/);
    }
    expect(BOARDS.WEI.sections.map((s) => s.title)).toEqual(["AMERICAS", "EMEA", "ASIA-PACIFIC"]);
  });
});

describe("FX crosses", () => {
  // Units of each currency per 1 USD.
  const perUsd = { USD: 1, EUR: 0.86, JPY: 150.5, INR: 88.0 };

  it("triangulates through USD", () => {
    expect(crossRate(perUsd, "USD", "JPY")).toBe(150.5);
    expect(crossRate(perUsd, "EUR", "USD")).toBeCloseTo(1 / 0.86, 12);
    expect(crossRate(perUsd, "EUR", "JPY")).toBeCloseTo(150.5 / 0.86, 12);
    expect(crossRate(perUsd, "INR", "INR")).toBe(1);
  });

  it("is blank, not guessed, when a leg is missing", () => {
    expect(crossRate({ ...perUsd, JPY: null }, "EUR", "JPY")).toBeNull();
    expect(crossRate(perUsd, "EUR", "CHF")).toBeNull();
    expect(crossRate({ ...perUsd, EUR: 0 }, "EUR", "JPY")).toBeNull();
  });

  it("maps legs and pairs to Yahoo symbols", () => {
    expect(usdLeg("USD")).toBeNull();
    expect(usdLeg("INR")).toBe("USDINR=X");
    expect(crossPair("EUR", "JPY")).toBe("EURJPY=X");
    expect(crossPair("USD", "USD")).toBe("DX-Y.NYB");
  });

  it("parses the currency list", () => {
    expect(parseCurrencies([])).toEqual({ ok: true, list: FXC_DEFAULT });
    expect(parseCurrencies(["eur", "inr", "EUR"])).toEqual({ ok: true, list: ["EUR", "INR"] });
    expect(parseCurrencies(["EU"])).toMatchObject({ ok: false });
    expect(parseCurrencies(Array.from({ length: 17 }, (_, i) => "A" + String.fromCharCode(65 + i) + "X"))).toMatchObject({ ok: false });
  });
});

describe("fmtRate", () => {
  it("shows enough digits for each magnitude", () => {
    expect(fmtRate(1.08523)).toBe("1.0852");
    expect(fmtRate(150.512)).toBe("150.51");
    expect(fmtRate(12.3456)).toBe("12.346");
    expect(fmtRate(0.011364)).toBe("0.011364");
    expect(fmtRate(0.6523)).toBe("0.65230");
    expect(fmtRate(1234.5)).toBe("1,234.50");
    expect(fmtRate(null)).toBe("—");
  });
});

describe("newsQuery", () => {
  it("picks top, symbol or keyword", () => {
    expect(newsQuery([], undefined)).toEqual({ kind: "top" });
    expect(newsQuery([], { symbol: "AAPL" })).toEqual({ kind: "symbol", symbol: "AAPL" });
    expect(newsQuery(["top"], { symbol: "AAPL" })).toEqual({ kind: "top" });
    expect(newsQuery(["rate", "cut"], { symbol: "AAPL" })).toEqual({ kind: "keyword", q: "RATE CUT" });
  });
});
