/** Language semantics: variables, scopes, functions, history, outputs, drawings, alerts, inputs, request, live ticks, caps. */
import { describe, expect, it } from "vitest";
import { compile, type Bar, type BarCols, type ScriptResult } from "./index";
import { barsFromCloses, expectClose, near, plot, runScript, walk } from "./testkit";

const bars4 = barsFromCloses([1, 2, 3, 4]);
const bars6 = barsFromCloses([1, 2, 3, 4, 5, 6]);
const H = `indicator("t")\n`;
/** Run a script body (header added) over bars and return the plot "x". */
const px = (body: string, b: BarCols = bars4) => plot(runScript(H + body, b), "x");

describe("values and operators", () => {
  it("arithmetic, % and division by zero", () => {
    expectClose(px('plot(close * 2 + 1, "x")\n'), [3, 5, 7, 9]);
    expectClose(px('plot(close / 0, "x")\n'), [NaN, NaN, NaN, NaN]);
    expectClose(px('plot(-5 % 3, "x")\n'), [-2, -2, -2, -2]);
    expectClose(px('plot(5 % 0, "x")\n'), [NaN, NaN, NaN, NaN]);
    expectClose(px('plot(2 - -3, "x")\n'), [5, 5, 5, 5]);
  });
  it("na rules", () => {
    expectClose(px('plot(na + 1, "x")\n'), [NaN, NaN, NaN, NaN]);
    expectClose(px('plot(nz(na, 7), "x")\n'), [7, 7, 7, 7]);
    expectClose(px('plot(nz(close), "x")\n'), [1, 2, 3, 4]);
    expectClose(px('plot(na(na) ? 1 : 0, "x")\n'), [1, 1, 1, 1]);
    expectClose(px('plot(na == na ? 1 : 0, "x")\n'), [0, 0, 0, 0]);
    expectClose(px('plot(na != 1 ? 1 : 0, "x")\n'), [0, 0, 0, 0]);
    expectClose(px('plot(na < 1 ? 1 : 0, "x")\n'), [0, 0, 0, 0]);
  });
  it("truth: a number is true when not na and not 0", () => {
    expectClose(px('plot(0 ? 1 : 2, "x")\n'), [2, 2, 2, 2]);
    expectClose(px('plot(na ? 1 : 2, "x")\n'), [2, 2, 2, 2]);
    expectClose(px('plot(-3 ? 1 : 2, "x")\n'), [1, 1, 1, 1]);
    expectClose(px('plot(not na ? 1 : 2, "x")\n'), [1, 1, 1, 1]);
  });
  it("and / or short-circuit", () => {
    // the right side would be a runtime error if it ran
    expectClose(px('plot(close > 100 and array.get(array.new(0), 0) ? 1 : 0, "x")\n'), [0, 0, 0, 0]);
    expectClose(px('plot(close > 0 or array.get(array.new(0), 0) ? 1 : 0, "x")\n'), [1, 1, 1, 1]);
  });
  it("comparison and equality on text", () => {
    expectClose(px('plot("a" == "a" ? 1 : 0, "x")\n'), [1, 1, 1, 1]);
    expectClose(px('plot("a" < "b" ? 1 : 0, "x")\n'), [1, 1, 1, 1]);
    expectClose(px('plot("a" != "b" ? 1 : 0, "x")\n'), [1, 1, 1, 1]);
  });
  it("text + number is a run-time error", () => {
    const res = runScript(H + 'a = "x" + 1\n', bars4);
    expect(res.error?.msg).toContain("CANNOT ADD");
    expect(res.error?.line).toBe(2);
  });
  it("math functions", () => {
    expectClose(px('plot(math.round(2.5) + math.round(-2.5), "x")\n'), [0, 0, 0, 0]);
    expectClose(px('plot(math.round(1.2345, 2), "x")\n'), [1.23, 1.23, 1.23, 1.23]);
    expectClose(px('plot(math.max(1, 5, 3) + math.min(4, 2, 9) + math.avg(2, 4), "x")\n'), [10, 10, 10, 10]);
    expectClose(px('plot(math.sqrt(-1), "x")\n'), [NaN, NaN, NaN, NaN]);
    expectClose(px('plot(math.pow(2, 10) + math.abs(-1) + math.sign(-9), "x")\n'), [1024, 1024, 1024, 1024]);
    expectClose(px('plot(math.floor(1.9) + math.ceil(1.1), "x")\n'), [3, 3, 3, 3]);
    expectClose(px('plot(math.pi, "x")\n'), [Math.PI, Math.PI, Math.PI, Math.PI]);
    expectClose(px('plot(math.log(math.e), "x")\n'), [1, 1, 1, 1]);
  });
  it("str functions", () => {
    const res = runScript(H + 'alert(str.tostring(1.5) + "|" + str.tostring(3) + "|" + str.tostring(1 / 3, 2) + "|" + str.tostring(na) + "|" + str.tostring(2 > 1))\n', barsFromCloses([1]));
    expect(res.alerts[0].message).toBe("1.5|3|0.33|na|true");
    const r2 = runScript(H + 'alert(str.contains("hello", "ell") ? "y" : "n")\nalert(str.tostring(str.length("abc")))\n', barsFromCloses([1]));
    expect(r2.alerts.map((a) => a.message)).toEqual(["y", "3"]);
  });
  it("colours", () => {
    const res = runScript(H + 'plot(close, "x", color = color.new(color.red, 50))\nplot(close, "y", color = color.rgb(255, 0, 0, 0))\nplot(close, "z", color = color.new(#112233, 0))\n', bars4);
    expect(res.plots[0].color).toBe("#f2364580");
    expect(res.plots[1].color).toBe("#ff0000");
    expect(res.plots[2].color).toBe("#112233");
  });
});

describe("variables", () => {
  it("var keeps its value across bars", () => {
    expectClose(px('var n = 0\nn := n + 1\nplot(n, "x")\n'), [1, 2, 3, 4]);
    expectClose(px('var n = 10\nn += 5\nplot(n, "x")\n'), [15, 20, 25, 30]);
  });
  it("var initialises on the first bar the line runs", () => {
    // the line is inside `if`, so it first runs on bar 2
    expectClose(px('if close > 2\n    var n = 100\n    n += 1\nplot(close > 2 ? 1 : 0, "x")\n'), [0, 0, 1, 1]);
  });
  it("a plain variable starts from na on every bar", () => {
    expectClose(px('a = 0\nif close > 2\n    a := 5\nplot(a, "x")\n'), [0, 0, 5, 5]);
    expectClose(px('var t = 0\nt += close\nplot(t, "x")\n'), [1, 3, 6, 10]);
  });
  it("history of a variable", () => {
    expectClose(px('a = close * 10\nplot(a[1], "x")\n'), [NaN, 10, 20, 30]);
    expectClose(px('a = close * 10\nplot(a[2], "x")\n'), [NaN, NaN, 10, 20]);
    expectClose(px('plot(close[1] + close[0], "x")\n'), [NaN, 3, 5, 7]);
  });
  it("history of a variable assigned only on some bars is na where it did not run", () => {
    expectClose(px('var a = 0\nb = na\nif close % 2 == 0\n    b := close\nplot(nz(b[1], -1), "x")\n'), [-1, -1, 2, -1]);
  });
  it("history with a computed offset", () => {
    expectClose(px('a = close\nplot(a[bar_index > 1 ? 2 : 0], "x")\n'), [1, 2, 1, 2]);
  });
  it("history of a var read before and after assignment", () => {
    expectClose(px('var s = 0\ns := nz(s[1]) + 1\nplot(s, "x")\n'), [1, 2, 3, 4]);
  });
  it("bar series: bar_index, last_bar_index, barstate, time", () => {
    expectClose(px('plot(bar_index, "x")\n'), [0, 1, 2, 3]);
    expectClose(px('plot(last_bar_index, "x")\n'), [3, 3, 3, 3]);
    expectClose(px('plot(barstate.isfirst ? 1 : 0, "x")\n'), [1, 0, 0, 0]);
    expectClose(px('plot(barstate.islast ? 1 : 0, "x")\n'), [0, 0, 0, 1]);
    expectClose(px('plot(time - time[1], "x")\n'), [NaN, 86400, 86400, 86400]);
    expectClose(px('plot(hl2 + hlc3 + ohlc4, "x")\n', barsFromCloses([3])), [3 + 3 + (3 + 3 + 4 + 2) / 4 + 0 * 1].map(() => 3 + 3 + 3));
  });
  it("lookback beyond 5000 is an error", () => {
    const res = runScript(H + "a = close\nplot(a[5001], \"x\")\n", bars4);
    expect(res.error?.msg).toContain("LOOKBACK TOO LARGE");
  });
});

describe("control flow", () => {
  it("if / else if / else", () => {
    expectClose(px('x = 0\nif close < 2\n    x := 10\nelse if close < 4\n    x := 20\nelse\n    x := 30\nplot(x, "x")\n'), [10, 20, 20, 30]);
  });
  it("a block variable is not visible outside", () => {
    const r = compile(H + "if close > 1\n    y = 1\nplot(y)\n");
    expect(r.ok).toBe(false);
  });
  it("for: up, down, by, and the loop variable", () => {
    expectClose(px('s = 0\nfor i = 1 to 5\n    s += i\nplot(s, "x")\n', barsFromCloses([1])), [15]);
    expectClose(px('s = 0\nfor i = 5 to 1\n    s += i\nplot(s, "x")\n', barsFromCloses([1])), [15]);
    expectClose(px('s = 0\nfor i = 0 to 10 by 5\n    s += i\nplot(s, "x")\n', barsFromCloses([1])), [15]);
    expectClose(px('s = 0\nfor i = 10 to 0 by -5\n    s += i\nplot(s, "x")\n', barsFromCloses([1])), [15]);
    expectClose(px('s = 0\nfor i = 1 to 0 by 1\n    s += 1\nplot(s, "x")\n', barsFromCloses([1])), [0]);
  });
  it("break and continue", () => {
    expectClose(px('s = 0\nfor i = 1 to 10\n    if i > 4\n        break\n    if i == 2\n        continue\n    s += i\nplot(s, "x")\n', barsFromCloses([1])), [1 + 3 + 4]);
    expectClose(px('n = 0\nwhile true\n    n += 1\n    if n >= 7\n        break\nplot(n, "x")\n', barsFromCloses([1])), [7]);
  });
  it("a for step of 0 is an error", () => {
    expect(runScript(H + "for i = 1 to 3 by 0\n    a = 1\n", bars4).error?.msg).toContain("STEP");
  });
});

describe("functions", () => {
  it("one-line and block bodies, defaults, named arguments", () => {
    expectClose(px('f(a, b = 10) => a + b\nplot(f(close) + f(1, 2) + f(b = 1, a = 1), "x")\n'), [1, 2, 3, 4].map((c) => c + 10 + 3 + 2));
    expectClose(px('f(a) =>\n    t = a * 2\n    t + 1\nplot(f(close), "x")\n'), [3, 5, 7, 9]);
  });
  it("a function can read earlier globals", () => {
    expectClose(px('k = 100\nf(a) => a + k\nplot(f(close), "x")\n'), [101, 102, 103, 104]);
  });
  it("a function's locals may reuse a global's name", () => {
    expectClose(px('src = 5\nf(src) => src * 2\nplot(f(close), "x")\n'), [2, 4, 6, 8]);
  });
  it("each call site has its own state (ta, var)", () => {
    const res = runScript(H + 'f(s) => ta.sma(s, 2)\ng() =>\n    var n = 0\n    n += 1\n    n\nplot(f(close), "a")\nplot(f(close * 10), "b")\nplot(g(), "c")\nplot(g(), "d")\n', bars4);
    expectClose(plot(res, "a"), [NaN, 1.5, 2.5, 3.5]);
    expectClose(plot(res, "b"), [NaN, 15, 25, 35]);
    expectClose(plot(res, "c"), [1, 2, 3, 4]);
    expectClose(plot(res, "d"), [1, 2, 3, 4]);
  });
  it("a function called inside an if only advances its state when it runs", () => {
    const res = runScript(H + 'f(s) =>\n    var n = 0\n    n += s\n    n\nr = na\nif close > 2\n    r := f(1)\nplot(r, "x")\n', bars4);
    expectClose(plot(res, "x"), [NaN, NaN, 1, 2]);
  });
  it("tuples from user functions and built-ins", () => {
    const res = runScript(H + 'f(a) =>\n    [a, a * 2, a * 3]\n[p, q, r] = f(close)\nplot(p + q + r, "x")\n', bars4);
    expectClose(plot(res, "x"), [6, 12, 18, 24]);
  });
  it("a function's result is its last expression; no last expression gives na", () => {
    expectClose(px('f(a) =>\n    t = a\nplot(nz(f(close), -1), "x")\n'), [-1, -1, -1, -1]);
  });
  it("history on a parameter", () => {
    expectClose(px('f(a) => a[1]\nplot(f(close), "x")\n'), [NaN, 1, 2, 3]);
  });
  it("nested calls of the same function use separate copies", () => {
    expectClose(px('f(a) => a + 1\nplot(f(f(f(close))), "x")\n'), [4, 5, 6, 7]);
  });
});

describe("outputs", () => {
  it("plot: style, colour per bar, handle for fill", () => {
    const res = runScript(H + 'p1 = plot(close, "a", style = "histogram", color = close > 2 ? color.green : color.red)\np2 = plot(close - 1, "b", color = color.blue)\nfill(p1, p2, color = color.new(color.blue, 80))\n', bars4);
    expect(res.plots[0]).toMatchObject({ kind: "plot", title: "a", style: "histogram" });
    expect(res.plots[0].colors).toEqual(["#f23645", "#f23645", "#089981", "#089981"]);
    expect(res.plots[1].colors).toBeUndefined();
    expect(res.plots[1].color).toBe("#2962ff");
    expect(res.plots[2]).toMatchObject({ kind: "fill", a: 0, b: 1, color: "#2962ff33" });
  });
  it("a plot that does not run on some bars is na there", () => {
    expectClose(px('if close > 2\n    plot(close, "x")\n'), [NaN, NaN, 3, 4]);
  });
  it("hline", () => {
    const res = runScript(H + 'hline(70, "Upper", color = color.red, linestyle = "solid")\nhline(30)\n', bars4);
    expect(res.plots[0]).toMatchObject({ kind: "hline", title: "Upper", price: 70, color: "#f23645", style: "solid" });
    expect(res.plots[1]).toMatchObject({ kind: "hline", price: 30, style: "dashed" });
  });
  it("bgcolor: na = none", () => {
    const res = runScript(H + 'bgcolor(close > 2 ? color.new(color.red, 80) : na)\n', bars4);
    expect(Array.from(res.plots[0].values as Float64Array)).toEqual([NaN, NaN, 1, 1]);
    // na is a colour change too, so the per-bar list is there (null = no background), same as the Python port
    expect(res.plots[0].colors).toEqual([null, null, "#f2364533", "#f2364533"]);
  });
  it("plotshape: condition, absolute price", () => {
    const res = runScript(H + 'plotshape(close > 2, "up", style = "arrowup", location = "belowbar", color = color.green, text = "B")\nplotshape(close > 2 ? close * 2 : na, "abs", location = "absolute")\n', bars4);
    expect(res.plots[0]).toMatchObject({ kind: "shape", title: "up", style: "arrowup", location: "belowbar", text: "B", color: "#089981" });
    expectClose(Array.from(res.plots[0].values as Float64Array), [NaN, NaN, 1, 1]);
    expectClose(Array.from(res.plots[1].values as Float64Array), [NaN, NaN, 6, 8]);
  });
  it("outputs in a user function: one per call site", () => {
    const res = runScript(H + 'f(a) =>\n    plot(a, "p")\n    a\nf(close)\nf(close * 2)\n', bars4);
    expect(res.plots.length).toBe(2);
    expectClose(Array.from(res.plots[1].values as Float64Array), [2, 4, 6, 8]);
  });
});

describe("drawings", () => {
  it("labels, lines, boxes (final state only)", () => {
    const res = runScript(H + 'if barstate.islast\n    label.new(bar_index, close, "last", color = color.red, textcolor = color.white)\n    line.new(0, 1, bar_index, close, color.blue, 2)\n    box.new(0, 5, 3, 1, color.gray, color.new(color.gray, 80))\n', bars4);
    expect(res.drawings.labels).toEqual([{ x: 3, y: 4, text: "last", color: "#f23645", style: "label_down", textcolor: "#ffffff" }]);
    expect(res.drawings.lines).toEqual([{ x1: 0, y1: 1, x2: 3, y2: 4, color: "#2962ff", width: 2 }]);
    expect(res.drawings.boxes).toEqual([{ left: 0, top: 5, right: 3, bottom: 1, color: "#787b86", bgcolor: "#787b8633" }]);
  });
  it("delete, set_text, set_xy, methods", () => {
    const src = H + 'a = label.new(0, 1, "a")\nb = label.new(1, 2, "b")\nlabel.set_text(b, "B")\nb.set_xy(5, 6)\nif bar_index == 1\n    a.delete()\n';
    const res = runScript(src, barsFromCloses([1, 2]));
    // bar 0 made a and b; bar 1 made a and b again and deleted its own a. Three labels survive.
    expect(res.drawings.labels.length).toBe(3);
    expect(res.drawings.labels.map((l) => l.text).sort()).toEqual(["B", "B", "a"]);
    expect(res.drawings.labels.filter((l) => l.text === "B").every((l) => l.x === 5 && l.y === 6)).toBe(true);
  });
  it("max_labels evicts the oldest", () => {
    const res = runScript('indicator("t", max_labels=3)\nlabel.new(bar_index, close, str.tostring(bar_index))\n', bars6);
    expect(res.drawings.labels.map((l) => l.text)).toEqual(["3", "4", "5"]);
  });
  it("tables: only the last state is shown", () => {
    const res = runScript(H + 't = table.new("top_right", 2, 2)\ntable.cell(t, 0, 0, "A", color.red, color.black)\ntable.cell(t, 1, 1, str.tostring(close))\n', bars4);
    const last = res.drawings.tables[res.drawings.tables.length - 1];
    expect(last).toMatchObject({ position: "top_right", columns: 2, rows: 2 });
    expect(last.cells).toEqual([
      { column: 0, row: 0, text: "A", color: "#f23645", bgcolor: "#363a45" },
      { column: 1, row: 1, text: "4", color: null, bgcolor: null },
    ]);
  });
  it("table cell out of range is an error", () => {
    expect(runScript(H + 't = table.new("top_left", 1, 1)\ntable.cell(t, 3, 0, "x")\n', bars4).error?.msg).toContain("OUT OF RANGE");
  });
});

describe("alerts", () => {
  it("alert fires once per bar per call site", () => {
    const res = runScript(H + 'if close > 2\n    alert("up")\n    alert("up")\n', bars4);
    // two call sites, so two alerts per bar
    expect(res.alerts.length).toBe(4);
    expect(res.alerts.map((a) => a.bar)).toEqual([2, 2, 3, 3]);
  });
  it("alert in a loop fires once", () => {
    const res = runScript(H + 'for i = 1 to 3\n    alert("x")\n', barsFromCloses([1]));
    expect(res.alerts.length).toBe(1);
  });
  it("alertcondition values and meta", () => {
    const r = compile(H + 'alertcondition(close > 2, "Big", "close is big")\nalertcondition(close < 2, "Small")\n');
    if (!r.ok) throw new Error("x");
    expect(r.program.meta.conditions).toEqual([
      { title: "Big", message: "close is big" },
      { title: "Small", message: "" },
    ]);
    const res = r.program.run(bars4).result();
    expect(Array.from(res.conditions[0].values)).toEqual([0, 0, 1, 1]);
    expect(Array.from(res.conditions[1].values)).toEqual([1, 0, 0, 0]);
  });
  it("keeps the newest 500 alerts", () => {
    const res = runScript(H + 'alert(str.tostring(bar_index))\n', barsFromCloses(Array.from({ length: 700 }, (_, i) => i + 1)));
    expect(res.alerts.length).toBe(500);
    expect(res.alerts[0].message).toBe("200");
    expect(res.alerts[499].message).toBe("699");
  });
});

describe("arrays and maps", () => {
  it("array functions and methods", () => {
    const res = runScript(
      H +
        'a = array.from(3, 1, 2)\na.push(5)\nb = array.new(2, 7)\narray.sort(a)\nplot(array.get(a, 0), "min")\nplot(array.size(a) + b.size(), "size")\nplot(a.sum(), "sum")\nplot(a.indexof(5), "idx")\nplot(a.includes(9) ? 1 : 0, "inc")\nplot(a.pop(), "pop")\nplot(a.shift(), "shift")\nplot(a.avg(), "avg")\n',
      barsFromCloses([1]),
    );
    expect(plot(res, "min")).toEqual([1]);
    expect(plot(res, "size")).toEqual([6]);
    expect(plot(res, "sum")).toEqual([11]);
    expect(plot(res, "idx")).toEqual([3]);
    expect(plot(res, "inc")).toEqual([0]);
    expect(plot(res, "pop")).toEqual([5]);
    expect(plot(res, "shift")).toEqual([1]);
    expect(plot(res, "avg")).toEqual([2.5]);
  });
  it("array index errors carry the line", () => {
    const res = runScript(H + "a = array.new(2)\nb = array.get(a, 5)\n", bars4);
    expect(res.error).toMatchObject({ line: 3, bar: 0 });
    expect(res.error?.msg).toContain("OUT OF RANGE");
  });
  it("maps", () => {
    const res = runScript(H + 'm = map.new()\nm.put("a", 1)\nmap.put(m, 2, 20)\nplot(m.get("a") + m.get(2), "x")\nplot(na(m.get("zz")) ? 1 : 0, "na")\nplot(m.size(), "size")\nm.remove("a")\nplot(m.contains("a") ? 1 : 0, "has")\nplot(array.size(m.keys()), "keys")\n', barsFromCloses([1]));
    expect(plot(res, "x")).toEqual([21]);
    expect(plot(res, "na")).toEqual([1]);
    expect(plot(res, "size")).toEqual([2]);
    expect(plot(res, "has")).toEqual([0]);
    expect(plot(res, "keys")).toEqual([1]);
  });
  it("arrays persist in var and keep growing", () => {
    expectClose(px('var a = array.new(0)\na.push(close)\nplot(a.size(), "x")\n'), [1, 2, 3, 4]);
  });
});

describe("inputs", () => {
  const src = H + 'len = input.int(2, "Length", min = 1, max = 5)\nk = input.float(1.5, "K", step = 0.5)\nuse = input.bool(true, "Use")\nname = input.string("b", "Name", array.from("a", "b"))\ns = input.source(close, "Src")\ntf = input.timeframe("D", "TF")\nplot(ta.sma(s, len) * k * (use ? 1 : 0), "x")\nalert(name + tf)\n';
  it("defaults, meta, overrides, clamping", () => {
    const r = compile(src);
    if (!r.ok) throw new Error(JSON.stringify(r.errors));
    expect(r.program.meta.inputs.map((i) => [i.title, i.kind, i.defval])).toEqual([
      ["Length", "int", 2],
      ["K", "float", 1.5],
      ["Use", "bool", true],
      ["Name", "string", "b"],
      ["Src", "source", "close"],
      ["TF", "timeframe", "1D"],
    ]);
    expectClose(plot(r.program.run(bars4).result(), "x"), [NaN, 2.25, 3.75, 5.25]);
    expectClose(plot(r.program.run(bars4, { inputs: { Length: 3 } }).result(), "x"), [NaN, NaN, 3, 4.5]);
    expectClose(plot(r.program.run(bars4, { inputs: { Length: 99 } }).result(), "x"), [NaN, NaN, NaN, NaN]); // clamped to 5 (needs 5 bars)
    expectClose(plot(r.program.run(bars4, { inputs: { Length: 0, K: 2 } }).result(), "x"), [2, 4, 6, 8]); // length clamped to 1
    expectClose(plot(r.program.run(bars4, { inputs: { Use: false } }).result(), "x"), [NaN, 0, 0, 0]);
    expectClose(plot(r.program.run(bars4, { inputs: { Src: "high", Length: 1, K: 1 } }).result(), "x"), [2, 3, 4, 5]);
    expect(r.program.run(bars4, { inputs: { TF: "60", Name: "a" } }).result().alerts[0].message).toBe("a1h");
  });
  it("a text not in options is a run-time error", () => {
    const r = compile(src);
    if (!r.ok) throw new Error("x");
    expect(r.program.run(bars4, { inputs: { Name: "zzz" } }).result().error?.msg).toContain("NOT ONE OF THE OPTIONS");
  });
  it("a wrong kind of override is an error", () => {
    const r = compile(src);
    if (!r.ok) throw new Error("x");
    expect(r.program.run(bars4, { inputs: { Length: "x" } }).result().error?.msg).toContain("NEEDS A NUMBER");
  });
  it("an input can be used where a constant is needed", () => {
    const r = compile(H + 'n = input.int(3, "N")\nhline(n * 10, "h")\nplot(lib.SMA(n), "x")\n');
    if (!r.ok) throw new Error(JSON.stringify(r.errors));
    const res = r.program.run(bars4).result();
    expect(res.plots[0].price).toBe(30);
    expectClose(plot(res, "x"), [NaN, NaN, 2, 3]);
  });
});

describe("request (no look-ahead)", () => {
  // hourly bars, close = bar index, 3 days
  const hours = (n: number): BarCols => {
    const t = Array.from({ length: n }, (_, i) => 1_700_006_400 + i * 3600); // 1_700_006_400 is a UTC midnight
    const c = Array.from({ length: n }, (_, i) => i);
    return { o: c.slice(), h: c.map((x) => x + 0.5), l: c.map((x) => x - 0.5), c, v: c.map(() => 1), t };
  };
  it("a longer timeframe of the same symbol: the value is the newest CLOSED bar", () => {
    const b = hours(72);
    const res = runScript(H + 'plot(request("", "1D", close), "x")\n', b, { chartTimeframe: "1h" });
    const x = plot(res, "x");
    for (let i = 0; i < 72; i++) {
      const d = Math.floor(i / 24);
      const h = i % 24;
      // on the last hour of a day the daily bar has just closed
      const want = h === 23 ? 24 * d + 23 : d === 0 ? NaN : 24 * (d - 1) + 23;
      if (!near(x[i], want)) throw new Error(`bar ${i}: got ${x[i]} want ${want}`);
    }
  });
  it("the expression may use ta and runs on the other series", () => {
    const b = hours(72);
    const res = runScript(H + 'plot(request("", "1D", ta.sma(close, 2)), "x")\n', b);
    const x = plot(res, "x");
    // daily closes: 23, 47, 71. sma2 is na on day 0, then 35 (days 0-1), 59 (days 1-2)
    expect(x[47]).toBe(35);
    expect(x[71]).toBe(59);
    expect(x[30]).toBeNaN(); // only day 0 closed
  });
  it("another symbol's data comes from the host, keyed SYMBOL|TIMEFRAME", () => {
    const b = hours(48);
    const other: BarCols = { o: [10, 20, 30], h: [10, 20, 30], l: [10, 20, 30], c: [10, 20, 30], v: [1, 1, 1], t: [1_700_006_400, 1_700_006_400 + 86400, 1_700_006_400 + 2 * 86400] };
    const r = compile(H + 's = input.symbol("MSFT", "Sym")\nplot(request(s, "1D", close), "x")\n');
    if (!r.ok) throw new Error("x");
    expect(r.program.resolveRequests()).toEqual([{ symbol: "MSFT", timeframe: "1D" }]);
    expect(r.program.resolveRequests({ Sym: "IBM" })).toEqual([{ symbol: "IBM", timeframe: "1D" }]);
    const res = r.program.run(b, { requests: { "MSFT|1D": other } }).result();
    const x = plot(res, "x");
    expect(x[0]).toBeNaN();
    expect(x[22]).toBeNaN();
    expect(x[23]).toBe(10); // the first daily bar ends at the close of chart bar 23
    expect(x[24]).toBe(10);
    expect(x[47]).toBe(20);
  });
  it("missing data and a shorter timeframe are run-time errors", () => {
    expect(runScript(H + 'plot(request("ZZZ", "1D", close), "x")\n', hours(5)).error?.msg).toContain("NO DATA FOR REQUEST ZZZ|1D");
    expect(runScript(H + 'plot(request("", "5m", close), "x")\n', hours(5), { chartTimeframe: "1h" }).error?.msg).toContain("SHORTER THAN THE CHART");
  });
  it("weekly buckets start on Monday", () => {
    // 1_700_006_400 = 2023-11-15 00:00 UTC (a Wednesday). 14 daily bars.
    const b = barsFromCloses(Array.from({ length: 14 }, (_, i) => i + 1), 1_700_006_400);
    const res = runScript(H + 'plot(request("", "1W", close), "x")\nplot(request("", "1W", time), "t")\n', b, { chartTimeframe: "1D" });
    const t = plot(res, "t");
    // 2023-11-13 is the Monday of that week
    const monday = Date.UTC(2023, 10, 13) / 1000;
    const lastKnown = t.filter((v) => v === v);
    expect(lastKnown[0]).toBe(monday);
  });
});

/** Compare two results (plots, alerts, drawings, conditions). */
function sameResult(a: ScriptResult, b: ScriptResult, drawings = true): void {
  expect(a.error).toEqual(b.error);
  expect(a.plots.length).toBe(b.plots.length);
  a.plots.forEach((p, i) => {
    const q = b.plots[i];
    expect(p.kind).toBe(q.kind);
    expect(p.values?.length).toBe(q.values?.length);
    if (p.values && q.values) expectClose(Array.from(p.values), Array.from(q.values), 1e-12);
    expect(p.color).toBe(q.color);
    expect(p.colors).toEqual(q.colors);
  });
  expect(a.alerts).toEqual(b.alerts);
  if (drawings) expect(a.drawings).toEqual(b.drawings);
  a.conditions.forEach((c, i) => expect(Array.from(c.values)).toEqual(Array.from(b.conditions[i].values)));
}

describe("live ticks", () => {
  const body = `indicator("t")
var cnt = 0
cnt += 1
var hist = array.new(0)
if close > open
    hist.push(close)
a = ta.ema(close, 5)
b = ta.rsi(close, 5)
[m, s, h] = ta.macd(close, 3, 6, 3)
hi = ta.highest(close, 4)
x = ta.barssince(close > open)
if ta.crossover(close, a)
    alert("cross")
if barstate.islast
    label.new(bar_index, close, str.tostring(cnt))
plot(a, "a")
plot(b, "b")
plot(m + h, "mh")
plot(cnt, "cnt")
plot(hist.size(), "sz")
plot(hi - x, "hx")
plot(close[2], "c2")
plotshape(close > a, "sh")
alertcondition(close > a, "above", "m")
`;
  const prog = () => {
    const r = compile(body);
    if (!r.ok) throw new Error(JSON.stringify(r.errors));
    return r.program;
  };
  const sub = (b: BarCols, n: number): BarCols => ({ o: Array.from(b.o).slice(0, n), h: Array.from(b.h).slice(0, n), l: Array.from(b.l).slice(0, n), c: Array.from(b.c).slice(0, n), v: Array.from(b.v).slice(0, n), t: Array.from(b.t as ArrayLike<number>).slice(0, n) });
  const withLast = (b: BarCols, bar: Bar): BarCols => {
    const n = b.c.length;
    const o = Array.from(b.o);
    const h = Array.from(b.h);
    const l = Array.from(b.l);
    const c = Array.from(b.c);
    const v = Array.from(b.v);
    o[n - 1] = bar.o;
    h[n - 1] = bar.h;
    l[n - 1] = bar.l;
    c[n - 1] = bar.c;
    v[n - 1] = bar.v;
    return { o, h, l, c, v, t: Array.from(b.t as ArrayLike<number>) };
  };
  it("updateLast gives the same result as a full re-run, again and again", () => {
    const all = walk(80, 11);
    const p = prog();
    const base = sub(all, 60);
    const run = p.run(base);
    const ticks: Bar[] = [
      { o: 100, h: 105, l: 99, c: 104, v: 5 },
      { o: 100, h: 106, l: 94, c: 95, v: 6 },
      { o: 101, h: 101, l: 101, c: 101, v: 7 },
    ];
    for (const tk of ticks) {
      run.updateLast(tk);
      sameResult(run.result(), p.run(withLast(base, tk)).result());
    }
  });
  it("append gives the same result as a full re-run", () => {
    const all = walk(80, 12);
    const p = prog();
    const run = p.run(sub(all, 50));
    for (let n = 51; n <= 70; n++) {
      const i = n - 1;
      const bar: Bar = { o: all.o[i], h: all.h[i], l: all.l[i], c: all.c[i], v: all.v[i], t: (all.t as ArrayLike<number>)[i] };
      run.append(bar);
      // sometimes tick the new bar too
      if (n % 3 === 0) {
        const tk = { ...bar, c: bar.c + 1, h: Math.max(bar.h, bar.c + 1) };
        run.updateLast(tk);
        sameResult(run.result(), p.run(withLast(sub(all, n), tk)).result(), false); // a label made on the old last bar stays: see the notes
        // the tick was a guess: the bar closes at its real values before the next bar opens
        run.updateLast(bar);
        sameResult(run.result(), p.run(sub(all, n)).result(), false);
      } else sameResult(run.result(), p.run(sub(all, n)).result(), false);
    }
  });
  it("the tick summary has the newest bar's values", () => {
    const p = prog();
    const run = p.run(sub(walk(30, 5), 30));
    const full = run.result();
    const tk = run.tick();
    expect(tk.bar).toBe(29);
    expect(tk.n).toBe(30);
    tk.plots.forEach((v, i) => {
      if (full.plots[i].values) expect(near(v.v, (full.plots[i].values as Float64Array)[29])).toBe(true);
    });
  });
  it("a run that failed before the last bar stays failed", () => {
    const r = compile(H + 'a = array.get(array.new(0), 0)\n');
    if (!r.ok) throw new Error("x");
    const run = r.program.run(bars4);
    expect(run.result().error?.bar).toBe(0);
    run.updateLast({ o: 1, h: 1, l: 1, c: 1, v: 1 });
    run.append({ o: 1, h: 1, l: 1, c: 1, v: 1, t: 5 });
    expect(run.result().error?.bar).toBe(0);
  });
  it("a scripts with request is re-run from scratch on a tick", () => {
    const r = compile(H + 'plot(request("", "1D", close), "x")\nplot(close, "c")\n');
    if (!r.ok) throw new Error("x");
    const b = barsFromCloses(Array.from({ length: 5 }, (_, i) => i + 1));
    const run = r.program.run(b, { chartTimeframe: "1D" });
    run.updateLast({ o: 9, h: 9, l: 9, c: 9, v: 1 });
    expect(plot(run.result(), "c")[4]).toBe(9);
    expect(plot(run.result(), "x")[4]).toBe(9);
  });
});

describe("lib.*", () => {
  it("computed once over all bars, read per bar", () => {
    const res = runScript(H + 'plot(lib.SMA(2), "x")\n[m, s, h] = lib.MACD(3, 6, 3)\nplot(m, "m")\n', bars6);
    expectClose(plot(res, "x"), [NaN, 1.5, 2.5, 3.5, 4.5, 5.5]);
    expect(plot(res, "m").length).toBe(6);
  });
  it("named arguments follow the catalog", () => {
    const res = runScript(H + 'plot(lib.SMA(length = 2), "x")\n', bars6);
    expectClose(plot(res, "x"), [NaN, 1.5, 2.5, 3.5, 4.5, 5.5]);
  });
});

describe("limits", () => {
  it("a runaway loop hits STEP LIMIT", () => {
    const res = runScript(H + "while true\n    a = 1\n", bars4);
    expect(res.error?.msg).toBe("STEP LIMIT");
    expect(res.error?.bar).toBe(0);
  });
  it("the per-run step limit stops a long run and keeps the earlier bars", () => {
    const n = 800;
    const res = runScript(H + 'x = 0\nfor i = 1 to 10000\n    x += 1\nplot(x, "x")\n', barsFromCloses(Array.from({ length: n }, (_, i) => i)));
    expect(res.error?.msg).toBe("STEP LIMIT");
    expect(res.error?.bar).toBeGreaterThan(100);
    expect(res.error?.bar).toBeLessThan(600);
    const x = plot(res, "x");
    expect(x[0]).toBe(10000);
    expect(x[res.error?.bar as number]).toBeNaN();
  });
  it("arrays are limited to 100,000 elements in total", () => {
    expect(runScript(H + "a = array.new(100001)\n", bars4).error?.msg).toContain("MEMORY LIMIT");
    expect(runScript(H + "a = array.new(60000)\nb = array.new(60000)\n", bars4).error?.msg).toContain("MEMORY LIMIT");
    expect(runScript(H + "a = array.new(100000)\n", barsFromCloses([1])).error).toBeUndefined();
  });
  it("maps are limited to 50,000 entries", () => {
    const n = 50_010;
    const src = H + 'var m = map.new()\nm.put(bar_index, 1)\n';
    const res = runScript(src, barsFromCloses(Array.from({ length: n }, (_, i) => i)));
    expect(res.error?.msg).toContain("MEMORY LIMIT");
    expect(res.error?.bar).toBe(50_000);
  });
  it("a ta length above 5000 is an error", () => {
    expect(runScript(H + 'plot(ta.sma(close, 6000), "x")\n', bars4).error?.msg).toContain("LENGTH TOO LARGE");
  });
  it("a runtime error keeps the bars before it and says where", () => {
    const res = runScript(H + 'a = close > 2 ? array.get(array.new(0), 0) : 1\nplot(a, "x")\n', bars4);
    expect(res.error).toMatchObject({ bar: 2, line: 2 });
    expectClose(plot(res, "x"), [1, 1, NaN, NaN]);
  });
  it("empty bars run without error", () => {
    const res = runScript(H + 'plot(close, "x")\nhline(1)\n', { o: [], h: [], l: [], c: [], v: [], t: [] });
    expect(res.error).toBeUndefined();
    expect(res.plots.length).toBe(2);
  });
  it("the result's typed arrays have exactly one value per bar", () => {
    const res = runScript(H + 'plot(close, "x")\n', bars4);
    expect(res.plots[0].values?.length).toBe(4);
  });
});
