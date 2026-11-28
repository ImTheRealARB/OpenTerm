import { describe, expect, it } from "vitest";
import { chartCommand, chartSymbol, exportFileName, NAME_RE, parseScriptArgs, RESERVED, scriptName, STARTER } from "./scriptPanelArgs";

describe("SCRIPT words", () => {
  it("no words is the list", () => {
    expect(parseScriptArgs([])).toEqual({ mode: "list" });
  });
  it("NEW, NEW <EXAMPLE> and IMPORT, in any case", () => {
    expect(parseScriptArgs(["new"])).toEqual({ mode: "new" });
    expect(parseScriptArgs(["NEW", "sma_cross"])).toEqual({ mode: "new", example: "SMA_CROSS" });
    expect(parseScriptArgs(["import"])).toEqual({ mode: "import" });
  });
  it("a name opens the editor in capitals", () => {
    expect(parseScriptArgs(["my-rsi"])).toEqual({ mode: "edit", name: "MY-RSI" });
  });
  it("a bad name is an error that says what a name looks like", () => {
    const r = parseScriptArgs(["a b!"]);
    expect(r.mode).toBe("error");
    expect(parseScriptArgs(["-x"]).mode).toBe("error");
  });
});

describe("script names", () => {
  it("follow the stored-name rule: capitals, digits and _ . -, 1 to 32, starting with a letter or digit", () => {
    expect(scriptName(" my.script_1 ")).toBe("MY.SCRIPT_1");
    expect(scriptName("")).toBeNull();
    expect(scriptName("-A")).toBeNull();
    expect(scriptName("A".repeat(32))).toBe("A".repeat(32));
    expect(scriptName("A".repeat(33))).toBeNull();
    expect(NAME_RE.test("a")).toBe(false); // the regex wants capitals: scriptName upper-cases first
  });
  it("NEW and IMPORT are reserved", () => {
    for (const w of RESERVED) expect(scriptName(w.toLowerCase())).toBeNull();
  });
  it("the export file is the lower-case name with .ots", () => {
    expect(exportFileName("SMA_CROSS")).toBe("sma_cross.ots");
  });
});

describe("the chart command", () => {
  const view = (fn: string, symbol?: string) => ({ fn, security: symbol ? { symbol } : undefined });
  it("uses this panel's security first", () => {
    const panels = { 1: { views: [view("SCRIPT", "MSFT")], pos: 0 }, 2: { views: [view("GP", "TSLA")], pos: 0 } };
    expect(chartSymbol(panels, 1)).toBe("MSFT");
  });
  it("else the newest GP chart's security", () => {
    const panels = {
      1: { views: [view("SCRIPT")], pos: 0 },
      2: { views: [view("GP", "TSLA")], pos: 0 },
      3: { views: [view("Q", "IGNORED")], pos: 0 },
      4: { views: [view("GP", "NVDA")], pos: 0 },
    };
    expect(chartSymbol(panels, 1)).toBe("NVDA");
  });
  it("else AAPL", () => {
    expect(chartSymbol({ 1: { views: [view("SCRIPT")], pos: 0 } }, 1)).toBe("AAPL");
  });
  it("reads each panel's CURRENT view, not an older one in its history", () => {
    const panels = { 1: { views: [view("GP", "OLD"), view("SCRIPT")], pos: 1 }, 2: { views: [view("GP", "NEW")], pos: 0 } };
    expect(chartSymbol(panels, 1)).toBe("NEW");
  });
  it("is the command GP reads", () => {
    expect(chartCommand("AAPL", "MY-RSI")).toBe("AAPL GP SCRIPT=MY-RSI");
  });
});

describe("the starter text", () => {
  it("starts with a one-sentence comment, then indicator(...)", () => {
    const lines = STARTER.split("\n");
    expect(lines[0].startsWith("// ")).toBe(true);
    expect(lines[1].startsWith("indicator(")).toBe(true);
  });
});
