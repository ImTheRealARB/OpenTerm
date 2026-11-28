import { describe, expect, it } from "vitest";
import type { InputDef } from "./checker";
import { formText, inputsFromRaw, rawFromTexts } from "./inputArgs";
import { historyInterval, requestRange, scriptChartTf } from "./hostTf";

const defs: InputDef[] = [
  { title: "Length", kind: "int", defval: 14 },
  { title: "Level", kind: "float", defval: 70.5 },
  { title: "Smooth", kind: "bool", defval: true },
  { title: "Name", kind: "string", defval: "a" },
];

describe("inputsFromRaw", () => {
  it("types each value by the input's kind; empty slots keep the default", () => {
    expect(inputsFromRaw(defs, ["20", "", "false", "b"])).toEqual({ values: { Length: 20, Smooth: false, Name: "b" }, errors: [] });
    expect(inputsFromRaw(defs, [])).toEqual({ values: {}, errors: [] });
  });
  it("names the input that has a bad value and never guesses", () => {
    const r = inputsFromRaw(defs, ["x", "1e999x", "maybe"]);
    expect(r.errors).toEqual(["LENGTH NEEDS A NUMBER", "LEVEL NEEDS A NUMBER", "SMOOTH NEEDS TRUE OR FALSE"]);
    expect(r.values).toEqual({});
  });
  it("refuses more values than the script has inputs", () => {
    expect(inputsFromRaw(defs, ["1", "2", "true", "n", "extra"]).errors[0]).toBe("TOO MANY INPUTS: THE SCRIPT HAS 4, YOU GAVE 5");
  });
});

describe("rawFromTexts / formText", () => {
  it("drops boxes equal to the default and the trailing empties", () => {
    expect(rawFromTexts(defs, ["14", "70.5", "true", "a"])).toEqual([]);
    expect(rawFromTexts(defs, ["20", "70.5", "false", "a"])).toEqual(["20", "", "false"]);
    expect(rawFromTexts(defs, [" 20 ", "", "", ""])).toEqual(["20"]);
  });
  it("shows the override, else the default", () => {
    expect(formText(defs[0], ["20"], 0)).toBe("20");
    expect(formText(defs[1], ["20"], 1)).toBe("70.5");
    expect(formText(defs[2], [], 2)).toBe("true");
  });
});

describe("timeframe spelling", () => {
  it("maps chart intervals to script timeframes (and has none for the odd ones)", () => {
    expect(scriptChartTf("60m")).toBe("1h");
    expect(scriptChartTf("1d")).toBe("1D");
    expect(scriptChartTf("1wk")).toBe("1W");
    expect(scriptChartTf("90m")).toBeUndefined();
  });
  it("maps script timeframes back to history intervals", () => {
    expect(historyInterval("1h")).toBe("60m");
    expect(historyInterval("60")).toBe("60m");
    expect(historyInterval("D")).toBe("1d");
    expect(historyInterval("W")).toBe("1wk");
    expect(historyInterval("7x")).toBeUndefined();
  });
  it("asks for at least a year of daily bars, never less than the chart's range", () => {
    expect(requestRange("1D", "1M")).toBe("1Y");
    expect(requestRange("1D", "5Y")).toBe("5Y");
    expect(requestRange("1W", "1Y")).toBe("5Y");
    expect(requestRange("5m", "5D")).toBe("5D");
  });
});
