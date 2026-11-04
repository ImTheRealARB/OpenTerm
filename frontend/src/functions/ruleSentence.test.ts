import { describe, expect, it } from "vitest";
import { parseRule } from "../bt/ruleParse";
import cases from "./ruleSentence.cases.json";
import {
  defaultOperand, emptyClause, formError, formToRule, formToSentence, ruleToForm, ruleToSentence, sentenceFormToRule,
  type Clause, type Form, type Op, type Operand,
} from "./ruleSentence";

const op = (kind: Operand["kind"], n = 0): Operand => ({ kind, n });
const cl = (left: Operand, o: Op, right: Operand): Clause => ({ left, op: o, right });

describe("shared cases (also read by backend/tests/test_rule_sentence_cases.py)", () => {
  for (const c of cases.cases) {
    it(`${c.rule}`, () => {
      expect(parseRule(c.rule).ok).toBe(true);
      expect(ruleToSentence(c.rule)).toBe(c.sentence);
      const form = ruleToForm(c.rule)!;
      const canon = formToRule(form);
      expect(canon).toBe(c.canon);
      expect(parseRule(canon).ok).toBe(true);
      // form -> rule -> form is stable
      expect(ruleToForm(canon)).toEqual(form);
      expect(formToRule(ruleToForm(canon)!)).toBe(canon);
      expect(formError(form)).toBeNull();
    });
  }
  it("returns null for rules the grammar rejects or that name a saved strategy", () => {
    for (const r of cases.invalid) expect(ruleToSentence(r), r).toBeNull();
  });
});

const FORMS: { form: Form; rule: string; sentence: string }[] = [
  { form: { buy: [[cl(op("sma", 20), "crosses above", op("sma", 50))]] }, rule: "SMA20 CROSS> SMA50", sentence: "Buy when the 20-day average crosses above the 50-day average; sell when it crosses back below." },
  { form: { buy: [[cl(op("sma", 20), "crosses below", op("sma", 50))]] }, rule: "SMA20 CROSS< SMA50", sentence: "Buy when the 20-day average crosses below the 50-day average; sell when it crosses back above." },
  { form: { buy: [[cl(op("price"), "is above", op("sma", 200))]] }, rule: "CLOSE > SMA200", sentence: "Buy when the price is above the 200-day average; sell when that stops being true." },
  { form: { buy: [[cl(op("price"), "is below", op("ema", 10))]] }, rule: "CLOSE < EMA10", sentence: "Buy when the price is below the 10-day exponential average; sell when that stops being true." },
  { form: { buy: [[cl(op("rsi", 14), "is below", op("number", 30))]] }, rule: "RSI14 < 30", sentence: "Buy when the 14-day RSI is below 30; sell when that stops being true." },
  { form: { buy: [[cl(op("rsi", 14), "is at least", op("number", 70))]] }, rule: "RSI14 >= 70", sentence: "Buy when the 14-day RSI is at least 70; sell when that stops being true." },
  { form: { buy: [[cl(op("rsi", 14), "is at most", op("number", 30.5))]] }, rule: "RSI14 <= 30.5", sentence: "Buy when the 14-day RSI is at most 30.5; sell when that stops being true." },
  { form: { buy: [[cl(op("rsi", 14), "crosses above", op("number", 30))]] }, rule: "RSI14 CROSS> 30", sentence: "Buy when the 14-day RSI crosses above 30; sell when it crosses back below." },
  { form: { buy: [[cl(op("ema", 12), "crosses above", op("ema", 26))]] }, rule: "EMA12 CROSS> EMA26", sentence: "Buy when the 12-day exponential average crosses above the 26-day exponential average; sell when it crosses back below." },
  { form: { buy: [[cl(op("price"), "is above", op("highn", 20))]] }, rule: "CLOSE > HIGH20", sentence: "Buy when the price is above the 20-day high; sell when that stops being true." },
  { form: { buy: [[cl(op("price"), "is below", op("lown", 20))]] }, rule: "CLOSE < LOW20", sentence: "Buy when the price is below the 20-day low; sell when that stops being true." },
  { form: { buy: [[cl(op("ret", 10), "is above", op("number", 0))]] }, rule: "RET10 > 0", sentence: "Buy when the 10-day return is above 0; sell when that stops being true." },
  { form: { buy: [[cl(op("volume"), "is above", op("number", 1000000))]] }, rule: "VOLUME > 1000000", sentence: "Buy when the volume is above 1000000; sell when that stops being true." },
  { form: { buy: [[cl(op("open"), "is above", op("price"))]] }, rule: "OPEN > CLOSE", sentence: "Buy when the opening price is above the price; sell when that stops being true." },
  { form: { buy: [[cl(op("high"), "is above", op("highn", 5))]] }, rule: "HIGH > HIGH5", sentence: "Buy when the day's high is above the 5-day high; sell when that stops being true." },
  { form: { buy: [[cl(op("low"), "is below", op("lown", 5))]] }, rule: "LOW < LOW5", sentence: "Buy when the day's low is below the 5-day low; sell when that stops being true." },
  { form: { buy: [[cl(op("number", 30), "is above", op("rsi", 14))]] }, rule: "30 > RSI14", sentence: "Buy when 30 is above the 14-day RSI; sell when that stops being true." },
  {
    form: { buy: [[cl(op("sma", 20), "crosses above", op("sma", 50)), cl(op("rsi", 14), "is below", op("number", 70))]] },
    rule: "SMA20 CROSS> SMA50 AND RSI14 < 70",
    sentence: "Buy when the 20-day average crosses above the 50-day average and the 14-day RSI is below 70; sell when that stops being true.",
  },
  {
    form: { buy: [[cl(op("rsi", 14), "is below", op("number", 30))], [cl(op("rsi", 14), "is above", op("number", 70))]] },
    rule: "RSI14 < 30 OR RSI14 > 70",
    sentence: "Buy when the 14-day RSI is below 30, or when the 14-day RSI is above 70; sell when that stops being true.",
  },
  {
    form: { buy: [[cl(op("price"), "is above", op("sma", 50)), cl(op("price"), "is above", op("sma", 200)), cl(op("rsi", 2), "is below", op("number", 10))]] },
    rule: "CLOSE > SMA50 AND CLOSE > SMA200 AND RSI2 < 10",
    sentence: "Buy when the price is above the 50-day average and the price is above the 200-day average and the 2-day RSI is below 10; sell when that stops being true.",
  },
  { form: { buy: [[cl(op("sma", 1000), "is above", op("sma", 1))]] }, rule: "SMA1000 > SMA1", sentence: "Buy when the 1000-day average is above the 1-day average; sell when that stops being true." },
  { form: { buy: [[cl(op("sma", 5), "is above", op("sma", 10))], [cl(op("sma", 5), "is below", op("sma", 3)), cl(op("price"), "is below", op("number", 100.25))]] }, rule: "SMA5 > SMA10 OR SMA5 < SMA3 AND CLOSE < 100.25", sentence: "Buy when the 5-day average is above the 10-day average, or when the 5-day average is below the 3-day average and the price is below 100.25; sell when that stops being true." },
];

describe("form -> rule -> sentence", () => {
  it("has at least 20 forms", () => expect(FORMS.length).toBeGreaterThanOrEqual(20));
  for (const f of FORMS) {
    it(f.rule, () => {
      const rule = sentenceFormToRule(f.form);
      expect(rule).toBe(f.rule);
      expect(parseRule(rule).ok).toBe(true); // the existing grammar accepts it
      expect(formToSentence(f.form)).toBe(f.sentence);
      expect(ruleToSentence(rule)).toBe(f.sentence);
      expect(ruleToForm(rule)).toEqual(f.form); // stable round trip
    });
  }
});

describe("formError", () => {
  it("flags an empty form, a bad period and a short RSI", () => {
    expect(formError({ buy: [[]] })).toBe("Add a condition.");
    expect(formError({ buy: [[cl(op("sma", 0), "is above", op("sma", 5))]] })).toMatch(/Periods/);
    expect(formError({ buy: [[cl(op("sma", 1001), "is above", op("sma", 5))]] })).toMatch(/Periods/);
    expect(formError({ buy: [[cl(op("sma", 2.5), "is above", op("sma", 5))]] })).toMatch(/Periods/);
    expect(formError({ buy: [[cl(op("rsi", 1), "is below", op("number", 30))]] })).toMatch(/RSI/);
    expect(formError({ buy: [[cl(op("rsi", 14), "is below", op("number", -1))]] })).toMatch(/number/);
    expect(formError({ buy: [[cl(op("rsi", 14), "is below", op("number", NaN))]] })).toMatch(/number/);
    expect(formError({ buy: [[emptyClause()]] })).toBeNull();
  });
  it("defaults give a valid operand for every kind", () => {
    for (const k of ["price", "open", "high", "low", "volume", "sma", "ema", "rsi", "highn", "lown", "ret", "number"] as const) {
      expect(formError({ buy: [[cl(defaultOperand(k), "is above", op("number", 1))]] })).toBeNull();
    }
  });
});
