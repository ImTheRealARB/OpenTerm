/**
 * Tests for the OpenTerm Script importer. Pure text in, text + report out, so they run in Node (vitest) with no DOM.
 *
 * Reading guide: `imp()` runs the importer; `out()` gives the result as a list of lines; `row()` gives the report row of an
 * input line. `onlyKnownNames()` is the safety net: every dotted built-in the importer lets through must exist in names.ts.
 */
import { describe, expect, it } from "vitest";
import { importScript, type ImportResult } from "./importer";
import { BY_NAME } from "./names";
import { compile } from "./index";

/** Run the importer on a template string (a leading newline is ignored so scripts can start on their own line). */
const imp = (s: string): ImportResult => importScript(s.replace(/^\n/, ""));
const out = (r: ImportResult): string[] => r.source.trimEnd().split("\n");
const row = (r: ImportResult, line: number) => {
  const found = r.report.find((x) => x.line === line);
  if (!found) throw new Error(`no report row for line ${line}`);
  return found;
};

/** Namespaces whose members must all exist in names.ts. */
const CHECKED = new Set(["ta", "math", "input", "color", "str", "array", "map", "label", "line", "box", "table", "request"]);

/** Every dotted name in the translated source (outside strings and comments) must be an OpenTerm built-in. */
function onlyKnownNames(source: string): void {
  const code = source
    .split("\n")
    .map((l) => l.replace(/"[^"]*"|'[^']*'/g, '""').replace(/\/\/.*$/, ""))
    .join("\n");
  for (const m of code.matchAll(/\b([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)\b/g)) {
    const name = m[1];
    if (CHECKED.has(name.split(".")[0])) expect(BY_NAME.has(name), `${name} is not in names.ts`).toBe(true);
  }
}

describe("header lines", () => {
  it("drops the version line and keeps the rest", () => {
    const r = imp(`
//@version=5
indicator("X")
plot(close)
`);
    expect(out(r)).toEqual(['indicator("X")', "plot(close)"]);
    expect(row(r, 1).status).toBe("dropped");
    expect(row(r, 2).status).toBe("ok");
  });

  it("renames study( to indicator( and marks it changed", () => {
    const r = imp('study("Old", overlay=true)\n');
    expect(out(r)).toEqual(['indicator("Old", overlay=true)']);
    expect(row(r, 1).status).toBe("changed");
    expect(row(r, 1).note).toContain("study is now indicator");
  });

  it("drops the indicator arguments OpenTerm does not have, with a note each", () => {
    const r = imp('indicator("RSI", shorttitle="R", overlay=false, format=format.price, precision=2, timeframe="")\n');
    expect(out(r)).toEqual(['indicator("RSI", overlay=false)']);
    const note = row(r, 1).note;
    for (const n of ["shorttitle", "format", "precision", "timeframe"]) expect(note).toContain(n);
    expect(row(r, 1).status).toBe("changed");
  });

  it("keeps title, overlay and max_labels (max_labels_count is renamed)", () => {
    const r = imp('indicator(title="T", overlay=true, max_labels_count=100)\n');
    expect(out(r)).toEqual(['indicator(title="T", overlay=true, max_labels=100)']);
  });

  it("maps positional study arguments by position, not by shifted slot", () => {
    const r = imp('study("T", "short", true)\n');
    // shorttitle is dropped, overlay is still the second OpenTerm parameter
    expect(out(r)).toEqual(['indicator("T", true)']);
  });
});

describe("other symbols and timeframes", () => {
  it("turns request.security into request and drops the extra arguments", () => {
    const r = imp('x = request.security(syminfo.tickerid, "D", close, lookahead=barmerge.lookahead_off, gaps=barmerge.gaps_on)\n');
    expect(out(r)).toEqual(['x = request("", "D", close)']);
    expect(row(r, 1).status).toBe("changed");
    expect(row(r, 1).note).toContain("lookahead");
  });

  it("drops a line that needs timeframe.period", () => {
    const r = imp('x = request.security("AAPL", timeframe.period, close)\nplot(close)\n');
    expect(out(r)).toEqual(["plot(close)"]);
    expect(row(r, 1).status).toBe("dropped");
    expect(row(r, 1).note).toContain("timeframe.period");
  });
});

describe("variables and blocks", () => {
  it("turns varip into var and keeps := var if else for while", () => {
    const r = imp(`
varip count = 0
var total = 0.0
for i = 0 to 9
    total += i
if total > 5
    count := count + 1
else
    count := 0
while count < 3
    count += 1
`);
    expect(out(r)[0]).toBe("var count = 0");
    expect(out(r).slice(1)).toEqual(
      [
        "var total = 0.0",
        "for i = 0 to 9",
        "    total += i",
        "if total > 5",
        "    count := count + 1",
        "else",
        "    count := 0",
        "while count < 3",
        "    count += 1",
      ],
    );
    expect(row(r, 1).status).toBe("changed");
    expect(row(r, 2).status).toBe("ok");
  });

  it("removes type words in front of a declaration", () => {
    const r = imp("float x = ta.sma(close, 14)\nvar int n = 0\nseries bool up = close > open\n");
    expect(out(r)).toEqual(["x = ta.sma(close, 14)", "var n = 0", "up = close > open"]);
    expect(row(r, 1).status).toBe("changed");
  });

  it("removes type words in function parameters", () => {
    const r = imp("avg2(float a, float b = 2) => (a + b) / 2\nplot(avg2(close, open))\n");
    expect(out(r)).toEqual(["avg2(a, b = 2) => (a + b) / 2", "plot(avg2(close, open))"]);
  });

  it("drops the type list of array.new<float> and renames array.new_float", () => {
    const r = imp("a = array.new<float>(0)\nb = array.new_float(3, 1.5)\narray.push(a, 1)\n");
    expect(out(r)).toEqual(["a = array.new(0)", "b = array.new(3, 1.5)", "array.push(a, 1)"]);
    onlyKnownNames(r.source);
  });

  it("turns ta.tr written without brackets into a call", () => {
    const r = imp("range = ta.tr\nplot(range)\n");
    expect(out(r)[0]).toBe("range = ta.tr()");
  });
});

describe("things OpenTerm does not have", () => {
  it("drops strategy( and every strategy.* line", () => {
    const r = imp(`
strategy("S", overlay=true)
len = input.int(10)
if ta.crossover(close, ta.sma(close, len))
    strategy.entry("L", strategy.long)
strategy.close_all()
x = strategy.position_size
plot(x)
`);
    expect(row(r, 1).status).toBe("dropped");
    expect(row(r, 1).note).toContain("strategy");
    expect(row(r, 4).status).toBe("dropped");
    expect(row(r, 5).status).toBe("dropped");
    expect(row(r, 6).status).toBe("dropped");
    // plot(x) uses a variable that was dropped
    expect(row(r, 7).status).toBe("dropped");
    expect(row(r, 7).note).toContain("uses x (dropped above)");
    expect(out(r).join("\n")).not.toContain("strategy");
  });

  it("drops a switch and its whole block, line by line, and keeps what follows", () => {
    const r = imp(`
a = 1
res = switch a
    1 => 10
    2 => 20
    => 0
plot(close)
`);
    expect(out(r)).toEqual(["a = 1", "plot(close)"]);
    expect(row(r, 2).status).toBe("dropped");
    expect(row(r, 2).note).toContain("switch");
    for (const n of [3, 4, 5]) {
      expect(row(r, n).status).toBe("dropped");
      expect(row(r, n).note).toContain("dropped block");
    }
    expect(row(r, 6).status).toBe("ok");
  });

  it("drops import, export, method, type and library with their blocks", () => {
    const r = imp(`
import user/lib/1 as lib
export f(x) => x
method m(float x) =>
    x * 2
type Point
    float x
    float y
library("L")
plot(close)
`);
    expect(out(r)).toEqual(["plot(close)"]);
    for (let n = 1; n <= 8; n++) expect(row(r, n).status).toBe("dropped");
  });

  it("drops a line with an unknown built-in and names it", () => {
    const r = imp("sk = ta.skewness(close, 20)\nplot(close)\n");
    expect(out(r)).toEqual(["plot(close)"]);
    expect(row(r, 1).note).toContain("ta.skewness");
  });

  it("drops later lines that use a dropped variable, even through a second variable", () => {
    const r = imp(`
sk = ta.skewness(close, 20)
scaled = sk * 2
plot(scaled, "S")
plot(close, "C")
`);
    expect(out(r)).toEqual(['plot(close, "C")']);
    expect(row(r, 2).note).toContain("uses sk (dropped above)");
    expect(row(r, 3).note).toContain("uses scaled (dropped above)");
    expect(row(r, 4).status).toBe("ok");
  });

  it("puts a placeholder in an if whose lines were all dropped, and drops the matching else", () => {
    const r = imp(`
up = ta.crossover(close, open)
if up
    strategy.entry("L", strategy.long)
plot(close)
if ta.cci(close, 5) > 0
    plot(open)
else
    plot(low)
plot(high)
`);
    expect(out(r)).toEqual(["up = ta.crossover(close, open)", "if up", "    _empty1 = na", "plot(close)", "plot(high)"]);
    expect(row(r, 2).status).toBe("changed");
    expect(row(r, 2).note).toContain("placeholder");
    for (const n of [5, 6, 7, 8]) expect(row(r, n).status).toBe("dropped");
    expect(row(r, 9).status).toBe("ok");
  });

  it("does not treat text inside a string or comment as code", () => {
    const r = imp(`
label.new(bar_index, high, "strategy.entry here")  // strategy.exit is only a comment
msg = 'switch import method'
// strategy.close_all() in a comment line
`);
    expect(out(r)).toEqual([
      'label.new(bar_index, high, "strategy.entry here")  // strategy.exit is only a comment',
      "msg = 'switch import method'",
      "// strategy.close_all() in a comment line",
    ]);
    for (const x of r.report) expect(x.status).toBe("ok");
  });
});

describe("arguments", () => {
  it("removes named arguments the OpenTerm built-in does not have", () => {
    const r = imp('plot(close, title="A", color=color.red, offset=2, display=display.none)\n');
    expect(out(r)).toEqual(['plot(close, title="A", color=color.red)']);
    expect(row(r, 1).status).toBe("changed");
    expect(row(r, 1).note).toContain("offset");
  });

  it("keeps a call untouched when every argument exists (original spacing too)", () => {
    const r = imp('plot( ta.sma(close,  20), "MA",   color = color.new(color.red, 50) )\n');
    expect(out(r)).toEqual(['plot( ta.sma(close,  20), "MA",   color = color.new(color.red, 50) )']);
    expect(row(r, 1).status).toBe("ok");
  });

  it("maps style constants to text and drops an argument whose constant has no equivalent", () => {
    const r = imp(`
plot(close, style=plot.style_histogram)
plot(close, style=plot.style_linebr)
plotshape(up, "U", shape.triangleup, location.belowbar, color.green, 0, "UP")
`);
    expect(out(r)).toEqual([
      'plot(close, style="histogram")',
      "plot(close)",
      'plotshape(up, "U", "triangleup", "belowbar", color.green, "UP")',
    ]);
    expect(row(r, 2).status).toBe("changed");
    expect(row(r, 2).note).toContain("plot.style_linebr");
    // the dropped offset argument did not shift the text argument
    expect(row(r, 3).note).toContain("offset");
  });

  it("drops the line when a required argument is an unsupported constant", () => {
    const r = imp("plot(strategy.position_size)\nplot(syminfo.mintick)\nplot(close)\n");
    expect(out(r)).toEqual(["plot(close)"]);
  });

  it("renames old input( by its default value and old argument names", () => {
    const r = imp(`
a = input(14, "Length", type=input.integer, minval=1)
b = input(1.5, "Factor")
c = input(true, "On")
d = input(close, "Source")
e = input.integer(5, "Five")
f = input.float(2.5, "Two", minval=0, maxval=10, step=0.5, tooltip="x", group="g")
`);
    expect(out(r)).toEqual([
      'a = input.int(14, "Length", min=1)',
      'b = input.float(1.5, "Factor")',
      'c = input.bool(true, "On")',
      'd = input.source(close, "Source")',
      'e = input.int(5, "Five")',
      'f = input.float(2.5, "Two", min=0, max=10, step=0.5)',
    ]);
    onlyKnownNames(r.source);
    for (const x of r.report) expect(x.status).toBe("changed");
  });

  it("gives old unprefixed names their namespace unless the script defines the name itself", () => {
    const r = imp(`
a = sma(close, 5)
b = abs(a - 1)
max(x, y) => x > y ? x : y
c = max(a, b)
`);
    expect(out(r)).toEqual(["a = ta.sma(close, 5)", "b = math.abs(a - 1)", "max(x, y) => x > y ? x : y", "c = max(a, b)"]);
    onlyKnownNames(r.source);
  });

  it("keeps colours, na, nz and str.tostring", () => {
    const r = imp(`
c1 = #ff9800
c2 = #2962ffaa
v = nz(close[1], 0)
s = str.tostring(v, "#.##")
t = na(v) ? color.new(color.red, 50) : na
`);
    expect(out(r)).toEqual([
      "c1 = #ff9800",
      "c2 = #2962ffaa",
      "v = nz(close[1], 0)",
      "s = str.tostring(v)",
      "t = na(v) ? color.new(color.red, 50) : na",
    ]);
    expect(row(r, 4).note).toContain("format");
    onlyKnownNames(r.source);
  });
});

describe("layout", () => {
  it("keeps comments, blank lines and indentation, and ends with one newline", () => {
    const r = imp(`
// my indicator
indicator("X")   // title

if close > open
    // green bar
    plot(close)   // draw it
`);
    expect(r.source).toBe(
      ['// my indicator', 'indicator("X")   // title', "", "if close > open", "    // green bar", "    plot(close)   // draw it", ""].join("\n"),
    );
    expect(r.report).toHaveLength(5);
  });

  it("reports multi-line statements line by line and keeps their layout", () => {
    const r = imp(`
plot(ta.sma(close, 14),
     "MA",
     offset=1)
plot(close)
`);
    expect(r.report.map((x) => x.line)).toEqual([1, 2, 3, 4]);
    expect(r.report.slice(0, 3).every((x) => x.status === "changed")).toBe(true);
    expect(out(r)).toEqual(['plot(ta.sma(close, 14), "MA")', "plot(close)"]);
  });

  it("copes with Windows line endings and an empty script", () => {
    const r = importScript('indicator("X")\r\nplot(close)\r\n');
    expect(r.source).toBe('indicator("X")\nplot(close)\n');
    expect(importScript("").source).toBe("\n");
  });
});

const SCRIPT_FOR_COMPILE = `
//@version=5
indicator("RSI + MACD", shorttitle="RM", overlay=false, precision=2)
len = input.int(14, "RSI length", minval=1, maxval=100, group="RSI")
src = input(close, "Source")
fast = input.int(12, "Fast")
slow = input.int(26, "Slow")
sig = input.int(9, "Signal")
r = ta.rsi(src, len)
[macdLine, signalLine, hist] = ta.macd(src, fast, slow, sig)
skew = ta.skewness(close, 20)
scaled = skew * 2
varip int ticks = 0
ticks += 1
col = r > 70 ? color.red : r < 30 ? color.green : color.gray
plot(r, "RSI", color=col, linewidth=2, offset=1)
plot(macdLine, "MACD", color=color.blue)
plot(signalLine, "Signal", color=color.new(color.orange, 20))
plot(scaled, "Skew")
hline(70, "Upper", color=color.red, linestyle=hline.style_dashed)
hline(30, "Lower", color=color.green, linestyle=hline.style_dashed)
bgcolor(hist > 0 ? color.new(color.green, 90) : na)
if ta.crossover(r, 30)
    alert("RSI up through 30", alert.freq_once_per_bar)
if ta.crossunder(r, 70)
    strategy.entry("short", strategy.short)
longCond = ta.crossover(macdLine, signalLine)
alertcondition(longCond, "MACD up", "MACD crossed up")
plotshape(longCond, "Up", shape.triangleup, location.belowbar, color.green, 0, "UP")
`;

describe("a realistic script", () => {
  const SCRIPT = SCRIPT_FOR_COMPILE;

  it("translates the supported lines and drops the rest with a reason", () => {
    const r = imp(SCRIPT);
    expect(out(r)).toEqual([
      'indicator("RSI + MACD", overlay=false)',
      'len = input.int(14, "RSI length", min=1, max=100)',
      'src = input.source(close, "Source")',
      'fast = input.int(12, "Fast")',
      'slow = input.int(26, "Slow")',
      'sig = input.int(9, "Signal")',
      "r = ta.rsi(src, len)",
      "[macdLine, signalLine, hist] = ta.macd(src, fast, slow, sig)",
      "var ticks = 0",
      "ticks += 1",
      "col = r > 70 ? color.red : r < 30 ? color.green : color.gray",
      'plot(r, "RSI", color=col, linewidth=2)',
      'plot(macdLine, "MACD", color=color.blue)',
      'plot(signalLine, "Signal", color=color.new(color.orange, 20))',
      'hline(70, "Upper", color=color.red, linestyle="dashed")',
      'hline(30, "Lower", color=color.green, linestyle="dashed")',
      "bgcolor(hist > 0 ? color.new(color.green, 90) : na)",
      "if ta.crossover(r, 30)",
      '    alert("RSI up through 30")',
      "if ta.crossunder(r, 70)",
      "    _empty1 = na",
      "longCond = ta.crossover(macdLine, signalLine)",
      'alertcondition(longCond, "MACD up", "MACD crossed up")',
      'plotshape(longCond, "Up", "triangleup", "belowbar", color.green, "UP")',
    ]);
    onlyKnownNames(r.source);
  });

  it("reports one row per input line with the right status", () => {
    const r = imp(SCRIPT);
    const lines = SCRIPT.replace(/^\n/, "").split("\n").filter((l) => l.trim() !== "");
    expect(r.report).toHaveLength(lines.length);
    // report lines are 1-based lines of the input
    expect(r.report[0].line).toBe(1);
    expect(r.report[0].status).toBe("dropped"); // version line
    const status = (n: number) => row(r, n).status;
    expect(status(2)).toBe("changed"); // indicator arguments
    expect(status(8)).toBe("ok"); // r = ta.rsi(...)
    expect(status(10)).toBe("dropped"); // ta.skewness
    expect(row(r, 10).note).toContain("ta.skewness");
    expect(status(11)).toBe("dropped"); // uses skew
    expect(status(12)).toBe("changed"); // varip int
    expect(status(13)).toBe("ok");
    expect(status(18)).toBe("dropped"); // uses scaled
    expect(status(23)).toBe("changed"); // alert extra argument
    expect(status(24)).toBe("changed"); // if with a placeholder
    expect(status(25)).toBe("dropped"); // strategy.entry
    expect(status(28)).toBe("changed"); // plotshape offset
    // nothing in the result mentions the dropped features
    expect(r.source).not.toMatch(/strategy|skew|varip|shorttitle/);
  });
});

describe("the result runs on the engine", () => {
  // The importer is only useful if what it writes compiles: these cover the realistic script, the empty-block placeholder
  // (`_emptyN = na`) and input options (written as array.from(...)).
  const errorsOf = (src: string) => {
    const c = compile(importScript(src.replace(/^\n/, "")).source);
    return c.ok ? [] : c.errors.map((e) => `${e.line}:${e.col} ${e.msg}`);
  };
  it("compiles the realistic script", () => {
    expect(errorsOf(SCRIPT_FOR_COMPILE)).toEqual([]);
  });
  it("compiles a block whose lines were all dropped", () => {
    expect(errorsOf('indicator("t")\nup = ta.crossover(close, open)\nif up\n    strategy.entry("L", strategy.long)\nplot(close)\n')).toEqual([]);
  });
  it("compiles input options", () => {
    expect(errorsOf('indicator("t")\nk = input.string("sma", "Type", options=["sma", "ema"])\nplot(k == "sma" ? ta.sma(close, 3) : ta.ema(close, 3))\n')).toEqual([]);
  });
});

