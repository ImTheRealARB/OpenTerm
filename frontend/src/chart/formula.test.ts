import { describe, expect, it } from "vitest";
import { evaluateFormula, MAX_FORMULA_LENGTH, parseFormula, validateFormula } from "./formula";
import { ema, rsi, sma } from "./indicators";
import { synth } from "./library/synth";
import { runIndicator } from "./library/catalog";

const cols = synth(200);
const ev = (src: string) => {
  const r = evaluateFormula(src, cols);
  if (!r.ok) throw new Error(`${r.error}`);
  return r.out;
};
const err = (src: string) => {
  const r = evaluateFormula(src, cols);
  if (r.ok) throw new Error("expected an error");
  return r;
};
const close = (a: Float64Array, b: Float64Array) => {
  for (let i = 0; i < a.length; i++) {
    if (Number.isNaN(b[i])) expect(Number.isNaN(a[i])).toBe(true);
    else expect(a[i]).toBeCloseTo(b[i], 9);
  }
};

describe("formula evaluation", () => {
  it("numbers and arithmetic with precedence", () => {
    expect(ev("1 + 2 * 3")[0]).toBe(7);
    expect(ev("(1 + 2) * 3")[0]).toBe(9);
    expect(ev("-2 ^ 2")[0]).toBe(-4);
    expect(ev("2 ^ 3 ^ 2")[0]).toBe(512);
    expect(ev("2 ^ -1")[0]).toBe(0.5);
    expect(ev("10 / 4")[0]).toBe(2.5);
    expect(ev("1.5e1 + .5")[0]).toBe(15.5);
    expect(Number.isNaN(ev("1 / 0")[0])).toBe(true);
  });

  it("columns, short names and derived prices", () => {
    close(ev("close"), cols.c);
    close(ev("C"), cols.c);
    close(ev("high - low"), cols.h.map((x, i) => x - cols.l[i]));
    close(ev("hl2"), cols.h.map((x, i) => (x + cols.l[i]) / 2));
    close(ev("ohlc4"), cols.c.map((x, i) => (cols.o[i] + cols.h[i] + cols.l[i] + x) / 4));
    close(ev("volume"), cols.v);
  });

  it("matches the library: MACD line, z-score, RSI, SMA and EMA", () => {
    close(ev("EMA(close,12) - EMA(close,26)"), ema(cols.c, 12).map((x, i) => x - ema(cols.c, 26)[i]));
    close(ev("RSI(close,14)"), rsi(cols.c, 14));
    close(ev("SMA(close,20)"), sma(cols.c, 20));
    const z = ev("(close - SMA(close,20)) / STDEV(close,20)");
    close(z, runIndicator("ZSCORE", cols, [20])![0]);
  });

  it("nests smoothers over computed series (leading NaN)", () => {
    const r = ev("EMA(RSI(close,14),5)");
    expect(Number.isFinite(r[199])).toBe(true);
    expect(Number.isNaN(r[10])).toBe(true);
  });

  it("comparison and boolean operators give 1 / 0 and NaN during warm-up", () => {
    const r = ev("RSI(close,14) > 70");
    expect(Number.isNaN(r[3])).toBe(true);
    for (let i = 20; i < 200; i++) expect(r[i] === 0 || r[i] === 1).toBe(true);
    expect(ev("1 < 2 AND 2 < 3")[0]).toBe(1);
    expect(ev("1 > 2 OR 2 > 3")[0]).toBe(0);
    expect(ev("NOT 1 > 2")[0]).toBe(1);
    expect(ev("3 = 3")[0]).toBe(1);
    expect(ev("3 != 3")[0]).toBe(0);
    expect(ev("not (1 == 2) and true")[0]).toBe(1);
  });

  it("IF, MAX, MIN, ABS, LOG, SQRT, POW", () => {
    expect(ev("IF(1 > 2, 10, 20)")[0]).toBe(20);
    close(ev("IF(close > open, 1, -1)"), cols.c.map((x, i) => (x > cols.o[i] ? 1 : -1)));
    expect(ev("MAX(3, 7)")[0]).toBe(7);
    expect(ev("MIN(3, 7)")[0]).toBe(3);
    expect(ev("ABS(-4)")[0]).toBe(4);
    expect(ev("LOG(100)")[0]).toBeCloseTo(2, 12);
    expect(ev("LN(1)")[0]).toBe(0);
    expect(ev("SQRT(81)")[0]).toBe(9);
    expect(ev("POW(2, 10)")[0]).toBe(1024);
    expect(Number.isNaN(ev("SQRT(-1)")[0])).toBe(true);
  });

  it("REF lags a series", () => {
    const r = ev("REF(close,1)");
    expect(Number.isNaN(r[0])).toBe(true);
    expect(r[5]).toBe(cols.c[4]);
    close(ev("close - REF(close,1)"), cols.c.map((x, i) => (i ? x - cols.c[i - 1] : NaN)));
  });

  it("CROSSOVER and CROSSUNDER", () => {
    const up = ev("CROSSOVER(close, SMA(close,10))");
    const dn = ev("CROSSUNDER(close, SMA(close,10))");
    const s = sma(cols.c, 10);
    for (let i = 11; i < 200; i++) {
      expect(up[i]).toBe(cols.c[i] > s[i] && cols.c[i - 1] <= s[i - 1] ? 1 : 0);
      expect(dn[i]).toBe(cols.c[i] < s[i] && cols.c[i - 1] >= s[i - 1] ? 1 : 0);
    }
    expect(up.some((x) => x === 1)).toBe(true);
  });

  it("calls any library indicator by id, with output selection", () => {
    close(ev("RSI(14)"), rsi(cols.c, 14));
    close(ev("MACD(12,26,9).signal"), runIndicator("MACD", cols, [12, 26, 9])![1]);
    close(ev("macd(12,26,9).hist + 0"), runIndicator("MACD", cols, [12, 26, 9])![2]);
    close(ev("ATR()"), runIndicator("ATR", cols)![0]);
    close(ev("BB(20, 2).upper - BB(20, 2).lower"), runIndicator("BB", cols, [20, 2])![1].map((x, i) => x - runIndicator("BB", cols, [20, 2])![2][i]));
  });

  it("never returns infinities", () => {
    const r = ev("LN(close - close)");
    expect(r.every((x) => Number.isNaN(x))).toBe(true);
    expect(ev("EXP(1000)").every(Number.isNaN)).toBe(true);
  });

  it("evaluating a bare column does not hand back the input buffer", () => {
    const r = ev("close");
    r[0] = -1;
    expect(cols.c[0]).not.toBe(-1);
  });
});

describe("formula errors", () => {
  it("unknown function and name carry a position", () => {
    expect(err("1 + FOO(close)")).toMatchObject({ error: "UNKNOWN FUNCTION FOO AT 5", pos: 4 });
    expect(err("close + banana")).toMatchObject({ error: "UNKNOWN NAME BANANA AT 9", pos: 8 });
  });
  it("syntax errors", () => {
    expect(err("EMA(close,").error).toBe("EXPECTED EXPRESSION AT 11");
    expect(err("EMA(close,12").error).toBe("EXPECTED ) AT 13");
    expect(err("(1 + 2").error).toBe("EXPECTED ) AT 7");
    expect(err("1 + * 2").error).toBe("UNEXPECTED * AT 5");
    expect(err("1 2").error).toBe("UNEXPECTED 2 AT 3");
    expect(err("1 + 2)").error).toBe("UNEXPECTED ) AT 6");
    expect(err("close $ 2").error).toBe("UNEXPECTED CHARACTER $ AT 7");
    expect(err("   ").error).toBe("EMPTY FORMULA AT 1");
  });
  it("arity and argument checks", () => {
    expect(err("IF(1,2)").error).toMatch(/^IF TAKES 3 ARGUMENTS AT 1/);
    expect(err("EMA(close,0)").error).toMatch(/LENGTH MUST BE/);
    expect(err("EMA(close,close)").error).toMatch(/MUST BE A NUMBER/);
    expect(err("EMA(close)").error).toMatch(/EMA TAKES/);
    expect(err("REF(close,-1)").error).toMatch(/REF SHIFT/);
    expect(err("MACD(12,26,9).nope").error).toMatch(/HAS NO OUTPUT NOPE/);
    expect(err("RSI(1,2,3,4)").error).toMatch(/AT MOST 1 PARAMETER/);
  });
  it("limits on length and depth", () => {
    expect(err("1+".repeat(300) + "1").error).toMatch(/LONGER THAN/);
    expect(MAX_FORMULA_LENGTH).toBe(500);
    expect(err("(".repeat(100) + "1" + ")".repeat(100)).error).toMatch(/^TOO DEEP/);
    expect(err("-".repeat(200) + "1").error).toMatch(/^TOO DEEP/);
  });
  it("no way to reach JavaScript", () => {
    for (const bad of ["constructor", "__proto__", "this", "window", "process"]) {
      expect(err(`${bad}`).error).toMatch(/^UNKNOWN NAME/);
      expect(err(`${bad}(1)`).error).toMatch(/^UNKNOWN FUNCTION/);
    }
    expect(err("close.constructor").ok).toBe(false);
    expect(err("[1]").ok).toBe(false);
    expect(err("1; 2").ok).toBe(false);
  });
  it("parseFormula / validateFormula agree with evaluation", () => {
    expect(parseFormula("EMA(close,12)-EMA(close,26)").ok).toBe(true);
    expect(parseFormula("EMA(close,")).toMatchObject({ ok: false, pos: 10 });
    expect(validateFormula("EMA(close,12)-EMA(close,26)").ok).toBe(true);
    expect(validateFormula("FOO(1)").ok).toBe(false);
    expect(validateFormula("EMA(close,200)").ok).toBe(true);
  });
});
