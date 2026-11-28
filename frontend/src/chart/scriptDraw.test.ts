import { describe, expect, it } from "vitest";
import { compile } from "../script/index";
import { barsFromCloses } from "../script/testkit";
import {
  allMarks, applyTick, buildModel, colorAt, countOutputs, cssColor, hasAlpha, hlineSpecs, lineSpecs, marksAtBar, paintScript, pointAt, scriptErrorText, tableRows, withAlpha,
  type Ctx2D, type PaintEnv, type ScriptModel,
} from "./scriptDraw";
import type { ThemeColors } from "./chartBase";

const theme = { bg: "#000", fg: "#fff", dim: "#888", up: "#0f0", down: "#f00", line: "#333", acc: "#ffa028", warn: "#fa0", sel: "#00f", val: "#eee", bar: "#111", grid: "#222", cup: "#0f0", cdown: "#f00", cline: "#fff", font: "mono", fs: 12 } as ThemeColors;
const H = `indicator("t")\n`;

function run(src: string, closes = [1, 2, 3, 4, 5]) {
  const c = compile(src);
  if (!c.ok) throw new Error(c.errors.map((e) => e.msg).join(";"));
  const bars = barsFromCloses(closes);
  const rs = c.program.run(bars);
  return { rs, program: c.program, bars, model: buildModel("T", rs.result(), bars.t as number[], theme) };
}

describe("colours", () => {
  it("turns 8 digit hex into rgba and leaves the rest alone", () => {
    expect(cssColor("#ff000080")).toBe("rgba(255,0,0,0.502)");
    expect(cssColor("#ff0000")).toBe("#ff0000");
    expect(cssColor(null)).toBeUndefined();
    expect(hasAlpha("#ff000080")).toBe(true);
    expect(hasAlpha("#ff0000")).toBe(false);
  });
});

describe("colour and error text helpers", () => {
  it("changes the opacity of hex and rgb colours only", () => {
    expect(withAlpha("#ff0000", 0.25)).toBe("rgba(255,0,0,0.25)");
    expect(withAlpha("rgba(1,2,3,0.9)", 0.1)).toBe("rgba(1,2,3,0.1)");
    expect(withAlpha("red", 0.1)).toBe("red");
  });
  it("names the script and says where the error is", () => {
    expect(scriptErrorText("RSI", { msg: "UNKNOWN NAME X", line: 3, col: 7 })).toBe("SCRIPT RSI: UNKNOWN NAME X (LINE 3:7)");
    expect(scriptErrorText("RSI", { msg: "BAD", line: 2, col: 1, bar: 40 }, 2)).toBe("SCRIPT RSI: BAD (LINE 2:1, BAR 40) +2 MORE");
    expect(scriptErrorText("RSI", { msg: "TOO MANY INPUTS", line: 0 })).toBe("SCRIPT RSI: TOO MANY INPUTS");
  });
});

describe("series, hlines, markers", () => {
  const src = H + 'plot(close, "a")\nplot(close * 2, "b", color.red, 2, "histogram")\nhline(3, "mid", color.blue, "dotted")\nplotshape(close > 3, "up", "triangleup", "belowbar", color.green, "UP")\n';
  const { model } = run(src);

  it("makes one series per plot with the script's colour or an accent default", () => {
    const l = lineSpecs(model);
    expect(l.map((x) => [x.title, x.kind, x.lineWidth])).toEqual([["a", "line", 1], ["b", "histogram", 2]]);
    expect(l[0].color).toBe(theme.acc); // no colour given: the first accent
    expect(l[1].color).toBe("#f23645");
    expect(l[0].points.map((p) => p.value)).toEqual([1, 2, 3, 4, 5]);
  });

  it("never defaults to the up / down colours", () => {
    const many = H + Array.from({ length: 7 }, (_, i) => `plot(close + ${i}, "p${i}")`).join("\n") + "\n";
    for (const s of lineSpecs(run(many).model)) expect([theme.up, theme.down]).not.toContain(s.color);
  });

  it("turns hline into a price line with its own line style", () => {
    expect(hlineSpecs(model)).toEqual([{ plot: 2, price: 3, color: "#2962ff", title: "mid", dash: "dotted" }]);
  });

  it("turns a shape output into markers only on the bars where it is true", () => {
    const marks = allMarks(model);
    expect(marks).toHaveLength(2);
    expect(marks[0]).toMatchObject({ position: "belowBar", shape: "arrowUp", text: "UP", color: "#089981" });
    expect(marksAtBar(model, 0)).toEqual([]);
  });

  it("leaves a gap where the script gave na", () => {
    const { model: m } = run(H + 'plot(close > 3 ? close : na, "x")\n');
    expect(lineSpecs(m)[0].points.map((p) => p.value)).toEqual([undefined, undefined, undefined, 4, 5]);
  });

  it("keeps a colour that changed per bar and puts it only on the points that differ", () => {
    const { model: m } = run(H + 'plot(close, "x", close > 3 ? color.red : color.green)\n');
    const pts = lineSpecs(m)[0].points;
    expect(colorAt(m.plots[0], 4)).toBe("#f23645");
    expect(colorAt(m.plots[0], 0)).toBe("#089981");
    expect(pts[4].color).toBe("#f23645");
  });
});

describe("counting", () => {
  it("counts plots, shapes, drawings and tables as outputs", () => {
    const { model } = run(H + 'plot(close, "a")\nplotshape(close > 3, "s")\nt = table.new("top_right", 1, 1)\ntable.cell(t, 0, 0, "hi")\n');
    expect(countOutputs(model)).toBe(2 + 1);
    expect(model.drawings.tables).toHaveLength(1);
  });
  it("lays a table out as rows of cells, empty where unset", () => {
    const { model } = run(H + 't = table.new("top_right", 2, 2)\ntable.cell(t, 1, 0, "A", color.red)\n');
    const rows = tableRows(model.drawings.tables[0]);
    expect(rows).toHaveLength(2);
    expect(rows[0].map((c) => c.text)).toEqual(["", "A"]);
    expect(rows[0][1].color).toBe("#f23645");
    expect(rows[1][0]).toEqual({ text: "", color: null, bgcolor: null });
  });
});

describe("live ticks", () => {
  const src = H + 'plot(close, "c")\nplotshape(close > 5, "big")\n';

  function ticking() {
    const t = run(src);
    const next = (m: ScriptModel, c: number, isNew: boolean, time: number) => {
      const bar = { o: c, h: c + 1, l: c - 1, c, v: 1, t: time };
      if (isNew) t.rs.append(bar);
      else t.rs.updateLast(bar);
      return applyTick(m, t.rs.tick(), time);
    };
    return { ...t, next };
  }

  it("an update changes the newest bar only and re-makes its marks", () => {
    const { model, next, bars } = ticking();
    const last = (bars.t as number[])[4];
    const d = next(model, 7, false, last);
    expect(d.resync).toBe(false);
    expect(d.grew).toBe(false);
    expect(d.points).toEqual([{ plot: 0, point: { time: last, value: 7 } }]);
    expect(d.marks).toHaveLength(1); // 7 > 5
    expect(model.plots[0].vals[3]).toBe(4); // older bars untouched
    expect(model.plots[0].vals[4]).toBe(7);
    const d2 = next(model, 3, false, last);
    expect(d2.marks).toEqual([]); // the condition went false again: the mark is gone
  });

  it("an append grows the model by one bar", () => {
    const { model, next, bars } = ticking();
    const t5 = (bars.t as number[])[4] + 86400;
    const d = next(model, 9, true, t5);
    expect(d.grew).toBe(true);
    expect(model.n).toBe(6);
    expect(model.times[5]).toBe(t5);
    expect(d.points[0].point).toEqual({ time: t5, value: 9 });
    expect(lineSpecs(model)[0].points).toHaveLength(6);
  });

  it("a tick that does not fit the model asks for a resync instead of guessing", () => {
    const { model, rs } = ticking();
    const tick = rs.tick();
    tick.plots.pop();
    expect(applyTick(model, tick, 0).resync).toBe(true);
    const t2 = rs.tick();
    t2.n = 99;
    expect(applyTick(model, t2, 0).resync).toBe(true);
  });

  it("pointAt reads the model after the tick", () => {
    const { model, next, bars } = ticking();
    next(model, 6, false, (bars.t as number[])[4]);
    expect(pointAt(model, model.plots[0], 4).value).toBe(6);
  });
});

/** A recording fake of the canvas context: what was painted, in order. Properties set on it are kept (and readable). */
function fakeCtx() {
  const log: string[] = [];
  const alphas: number[] = [];
  const props: Record<string, unknown> = {};
  const ctx = new Proxy(props, {
    get(t, k: string) {
      if (k === "measureText") return (s: string) => ({ width: s.length * 6 });
      if (k in t) return t[k];
      return (...a: unknown[]) => void log.push(`${k}(${a.map((x) => (typeof x === "number" ? Math.round(x) : x)).join(",")})`);
    },
    set(t, k: string, v) {
      if (k === "globalAlpha") alphas.push(v as number);
      t[k] = v;
      return true;
    },
  }) as unknown as Ctx2D;
  return { ctx, log, alphas };
}

const env = (over: Partial<PaintEnv> = {}): PaintEnv => ({
  w: 500, h: 300, priceH: 200, theme, visible: [0, 4],
  xOf: (i) => 50 + i * 20, yMain: (p) => 200 - p * 10, yOf: (_p, v) => 200 - v * 10, ...over,
});

describe("overlay painting", () => {
  it("paints stripes, fills, boxes, lines and labels, and counts them", () => {
    const { model } = run(
      H + 'a = plot(close, "a")\nb = plot(close - 1, "b")\nfill(a, b, color.new(color.blue, 80))\nbgcolor(close > 3 ? color.new(color.red, 80) : na)\n' +
      'if barstate.islast\n    label.new(bar_index, close, "L")\n    line.new(0, 1, 4, 5)\n    box.new(1, 4, 3, 2, color.red, color.new(color.red, 90))\n',
    );
    const { ctx, log } = fakeCtx();
    const n = paintScript(ctx, model, env());
    // 2 stripes (bars 3 and 4) + 1 fill polygon + 1 box + 1 line + 1 label
    expect(n).toBe(6);
    expect(log.filter((l) => l.startsWith("fillRect")).length).toBeGreaterThanOrEqual(2);
    expect(log.some((l) => l.startsWith("fillText(L"))).toBe(true);
    expect(log.some((l) => l.startsWith("clip"))).toBe(true); // drawings stay inside the price pane
  });

  it("paints nothing off screen or when the chart cannot place a bar", () => {
    const { model } = run(H + "bgcolor(color.new(color.red, 80))\n");
    expect(paintScript(fakeCtx().ctx, model, env({ visible: [10, 20] }))).toBe(0);
    expect(paintScript(fakeCtx().ctx, model, env({ xOf: () => null }))).toBe(0);
  });

  it("dims an opaque stripe so candles stay readable", () => {
    const { model } = run(H + "bgcolor(color.red)\n");
    const { ctx, alphas } = fakeCtx();
    paintScript(ctx, model, env());
    const dim = alphas.filter((a) => a !== 1);
    expect(dim.length).toBeGreaterThan(0);
    expect(Math.max(...dim)).toBeLessThan(0.5);
  });
});
