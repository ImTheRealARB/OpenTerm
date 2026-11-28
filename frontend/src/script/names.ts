/**
 * OpenTerm Script: the ONE list of built-in names (spec: docs/specs/PHASE_25.md section 1.5).
 *
 * Who reads it:
 *   - the TS engine (`script/checker.ts`) to know which names exist, their parameters and arity;
 *   - the editor (`script/editor.ts`) for auto-complete and hover docs;
 *   - the Python port, through `backend/tests/test_ts_mirrors.py`, which checks that the Python built-in set equals this list
 *     (minus `lib.*`, which is TS only in v1).
 * Add a built-in HERE first, then implement it in both engines.
 *
 * Pure data: no imports, so it is safe to load anywhere (it is still only imported by lazy chunks).
 */

/** What a name gives back. `tuple:N` = N values for `[a, b] = ...` destructuring. */
export type Ret =
  | "number"
  | "bool"
  | "string"
  | "color"
  | "void"
  | "plot"
  | "label"
  | "line"
  | "box"
  | "table"
  | "array"
  | "map"
  | "any"
  | "tuple:2"
  | "tuple:3";

export interface Param {
  name: string;
  /** Default value (as source text, e.g. "0", "na", '"line"'). Missing = required. */
  def?: string;
}

export interface Builtin {
  name: string;
  /** "var" = a value read without a call (close, math.pi, color.red); "fn" = called with (). */
  kind: "var" | "fn";
  params?: Param[];
  /** Takes any number of extra positional arguments after `params` (math.max, array.from). */
  variadic?: boolean;
  ret: Ret;
  /** Keeps state per call site (ta.*): cannot run inside a loop. */
  stateful?: boolean;
  /** Only allowed at the top level with constant arguments (input.*, alertcondition, indicator). */
  topLevel?: boolean;
  /** One plain sentence for the editor. */
  doc: string;
}

const v = (name: string, ret: Ret, doc: string): Builtin => ({ name, kind: "var", ret, doc });
const f = (name: string, params: Param[], ret: Ret, doc: string, extra: Partial<Builtin> = {}): Builtin => ({
  name,
  kind: "fn",
  params,
  ret,
  doc,
  ...extra,
});
const p = (name: string, def?: string): Param => (def === undefined ? { name } : { name, def });
const ta = (name: string, params: Param[], ret: Ret, doc: string): Builtin => f(name, params, ret, doc, { stateful: true });

/** Fixed colour values (both engines use these exact strings). */
export const COLORS: Record<string, string> = {
  red: "#f23645",
  green: "#089981",
  blue: "#2962ff",
  orange: "#ff9800",
  yellow: "#ffeb3b",
  purple: "#9c27b0",
  teal: "#00897b",
  aqua: "#00bcd4",
  lime: "#00e676",
  fuchsia: "#e040fb",
  maroon: "#880e4f",
  navy: "#311b92",
  olive: "#808000",
  silver: "#b2b5be",
  gray: "#787b86",
  white: "#ffffff",
  black: "#363a45",
};

export const PLOT_STYLES = ["line", "stepline", "histogram", "columns", "circles", "area"] as const;
export const SHAPE_STYLES = [
  "triangleup",
  "triangledown",
  "circle",
  "cross",
  "diamond",
  "arrowup",
  "arrowdown",
  "labelup",
  "labeldown",
] as const;
export const SHAPE_LOCATIONS = ["abovebar", "belowbar", "absolute"] as const;
export const TABLE_POSITIONS = ["top_left", "top_right", "bottom_left", "bottom_right"] as const;
export const SOURCES = ["open", "high", "low", "close", "volume", "hl2", "hlc3", "ohlc4"] as const;
/** Accepted timeframe spellings, normalised to the first form. */
export const TIMEFRAMES: Record<string, string> = {
  "1m": "1m", "1": "1m", "5m": "5m", "5": "5m", "15m": "15m", "15": "15m", "30m": "30m", "30": "30m",
  "1h": "1h", "60": "1h", "2h": "2h", "120": "2h", "4h": "4h", "240": "4h",
  "1D": "1D", "D": "1D", "1W": "1W", "W": "1W", "1M": "1M", "M": "1M",
};

export const BUILTINS: Builtin[] = [
  // ---- script header
  f("indicator", [p("title"), p("overlay", "false"), p("max_labels", "500")], "void", "Names the script; must be the first line.", {
    topLevel: true,
  }),

  // ---- bar series
  v("open", "number", "Open price of the bar."),
  v("high", "number", "Highest price of the bar."),
  v("low", "number", "Lowest price of the bar."),
  v("close", "number", "Closing price of the bar (the latest price on the live bar)."),
  v("volume", "number", "Volume of the bar."),
  v("time", "number", "Bar open time in epoch seconds."),
  v("hl2", "number", "(high + low) / 2."),
  v("hlc3", "number", "(high + low + close) / 3."),
  v("ohlc4", "number", "(open + high + low + close) / 4."),
  v("bar_index", "number", "Bar number, 0 for the oldest bar."),
  v("last_bar_index", "number", "Bar number of the newest bar."),
  v("barstate.isfirst", "bool", "True on the oldest bar."),
  v("barstate.islast", "bool", "True on the newest bar."),
  v("na", "number", "The missing value."),

  // ---- missing values
  f("na", [p("x")], "bool", "True when x is missing (na)."),
  f("nz", [p("x"), p("y", "0")], "number", "x, or y when x is missing."),

  // ---- math
  v("math.pi", "number", "3.14159..."),
  v("math.e", "number", "2.71828..."),
  f("math.abs", [p("x")], "number", "Absolute value."),
  f("math.ceil", [p("x")], "number", "Round up to a whole number."),
  f("math.floor", [p("x")], "number", "Round down to a whole number."),
  f("math.round", [p("x"), p("digits", "0")], "number", "Round half away from zero, to `digits` decimals."),
  f("math.sqrt", [p("x")], "number", "Square root."),
  f("math.pow", [p("x"), p("y")], "number", "x to the power y."),
  f("math.exp", [p("x")], "number", "e to the power x."),
  f("math.log", [p("x")], "number", "Natural logarithm."),
  f("math.log10", [p("x")], "number", "Base-10 logarithm."),
  f("math.max", [p("a"), p("b")], "number", "Largest of the values.", { variadic: true }),
  f("math.min", [p("a"), p("b")], "number", "Smallest of the values.", { variadic: true }),
  f("math.avg", [p("a"), p("b")], "number", "Mean of the values.", { variadic: true }),
  f("math.sign", [p("x")], "number", "1, 0 or -1."),

  // ---- ta (stateful per call site; exact rules in PHASE_25.md 1.6)
  ta("ta.sma", [p("src"), p("length")], "number", "Simple moving average."),
  ta("ta.ema", [p("src"), p("length")], "number", "Exponential moving average."),
  ta("ta.wma", [p("src"), p("length")], "number", "Weighted moving average (newest bar weighs most)."),
  ta("ta.rma", [p("src"), p("length")], "number", "Wilder's moving average (alpha 1/length)."),
  ta("ta.vwma", [p("src"), p("length")], "number", "Volume-weighted moving average."),
  ta("ta.rsi", [p("src"), p("length")], "number", "Relative strength index, 0 to 100."),
  ta("ta.stdev", [p("src"), p("length")], "number", "Standard deviation (population)."),
  ta("ta.variance", [p("src"), p("length")], "number", "Variance (population)."),
  ta("ta.highest", [p("src"), p("length")], "number", "Highest value over the last `length` bars."),
  ta("ta.lowest", [p("src"), p("length")], "number", "Lowest value over the last `length` bars."),
  ta("ta.change", [p("src"), p("length", "1")], "number", "src minus src `length` bars ago."),
  ta("ta.mom", [p("src"), p("length")], "number", "Momentum: src minus src `length` bars ago."),
  ta("ta.roc", [p("src"), p("length")], "number", "Rate of change in percent."),
  ta("ta.cum", [p("src")], "number", "Running total."),
  ta("ta.tr", [], "number", "True range of the bar."),
  ta("ta.atr", [p("length")], "number", "Average true range."),
  ta("ta.crossover", [p("a"), p("b")], "bool", "True on the bar where a moves above b."),
  ta("ta.crossunder", [p("a"), p("b")], "bool", "True on the bar where a moves below b."),
  ta("ta.cross", [p("a"), p("b")], "bool", "True on the bar where a and b cross either way."),
  ta("ta.rising", [p("src"), p("length")], "bool", "True when src is above each of its last `length` values."),
  ta("ta.falling", [p("src"), p("length")], "bool", "True when src is below each of its last `length` values."),
  ta("ta.barssince", [p("cond")], "number", "Bars since cond was last true."),
  ta("ta.valuewhen", [p("cond"), p("src"), p("occurrence", "0")], "number", "src on the bar where cond was last true."),
  ta("ta.linreg", [p("src"), p("length"), p("offset", "0")], "number", "Linear regression line value."),
  ta("ta.macd", [p("src"), p("fast"), p("slow"), p("signal")], "tuple:3", "MACD line, signal line and histogram."),
  ta("ta.bb", [p("src"), p("length"), p("mult")], "tuple:3", "Bollinger middle, upper and lower bands."),
  ta("ta.stoch", [p("src"), p("high"), p("low"), p("length")], "number", "Stochastic %K, 0 to 100."),

  // ---- inputs (top level, constant arguments; they build the settings form)
  f("input.int", [p("defval"), p("title"), p("min", "na"), p("max", "na"), p("step", "1")], "number", "A whole-number setting.", {
    topLevel: true,
  }),
  f("input.float", [p("defval"), p("title"), p("min", "na"), p("max", "na"), p("step", "na")], "number", "A number setting.", {
    topLevel: true,
  }),
  f("input.bool", [p("defval"), p("title")], "bool", "An on/off setting.", { topLevel: true }),
  f("input.string", [p("defval"), p("title"), p("options", "na")], "string", "A text setting, optionally from a list.", {
    topLevel: true,
  }),
  f("input.source", [p("defval"), p("title")], "number", "Pick a price series (open, high, low, close, hl2...).", {
    topLevel: true,
  }),
  f("input.symbol", [p("defval"), p("title")], "string", "A symbol setting.", { topLevel: true }),
  f("input.timeframe", [p("defval"), p("title")], "string", "A timeframe setting (1m 5m 15m 30m 1h 2h 4h 1D 1W 1M).", {
    topLevel: true,
  }),

  // ---- other symbols and timeframes
  f("request", [p("symbol"), p("timeframe"), p("expr")], "any", "expr on another symbol or a longer timeframe, no look-ahead."),

  // ---- outputs
  f(
    "plot",
    [p("series"), p("title", '""'), p("color", "na"), p("linewidth", "1"), p("style", '"line"')],
    "plot",
    "Draw a line (or histogram, columns, circles, area, stepline).",
  ),
  f("hline", [p("price"), p("title", '""'), p("color", "na"), p("linestyle", '"dashed"')], "void", "A horizontal line at a price.", {
    topLevel: true,
  }),
  f("fill", [p("plot1"), p("plot2"), p("color", "na")], "void", "Shade the area between two plots."),
  f("bgcolor", [p("color")], "void", "Colour the background of this bar (na = none)."),
  f(
    "plotshape",
    [p("cond"), p("title", '""'), p("style", '"triangleup"'), p("location", '"abovebar"'), p("color", "na"), p("text", '""')],
    "void",
    "Draw a shape on bars where cond is true.",
  ),

  // ---- drawings (x = bar_index)
  f(
    "label.new",
    [p("x"), p("y"), p("text", '""'), p("color", "na"), p("style", '"label_down"'), p("textcolor", "na")],
    "label",
    "A text label at bar x, price y.",
  ),
  f("label.delete", [p("id")], "void", "Remove a label."),
  f("label.set_text", [p("id"), p("text")], "void", "Change a label's text."),
  f("label.set_xy", [p("id"), p("x"), p("y")], "void", "Move a label."),
  f("line.new", [p("x1"), p("y1"), p("x2"), p("y2"), p("color", "na"), p("width", "1")], "line", "A line between two points."),
  f("line.delete", [p("id")], "void", "Remove a line."),
  f("line.set_xy2", [p("id"), p("x"), p("y")], "void", "Move a line's second point."),
  f(
    "box.new",
    [p("left"), p("top"), p("right"), p("bottom"), p("color", "na"), p("bgcolor", "na")],
    "box",
    "A rectangle from bar left to bar right, price top to bottom.",
  ),
  f("box.delete", [p("id")], "void", "Remove a box."),
  f("table.new", [p("position"), p("columns"), p("rows")], "table", "A table in a corner of the chart."),
  f(
    "table.cell",
    [p("id"), p("column"), p("row"), p("text", '""'), p("color", "na"), p("bgcolor", "na")],
    "void",
    "Set one table cell.",
  ),

  // ---- alerts
  f("alert", [p("message")], "void", "Fire an alert (the chart fires it for the newest bar only)."),
  f("alertcondition", [p("cond"), p("title"), p("message", '""')], "void", "A named condition you can attach an alert to.", {
    topLevel: true,
  }),

  // ---- colours
  ...Object.keys(COLORS).map((k) => v(`color.${k}`, "color", `The colour ${k}.`)),
  f("color.new", [p("color"), p("transp")], "color", "The colour with transparency 0 (solid) to 100 (invisible)."),
  f("color.rgb", [p("r"), p("g"), p("b"), p("transp", "0")], "color", "A colour from red, green, blue (0 to 255)."),

  // ---- strings
  f("str.tostring", [p("x"), p("decimals", "-1")], "string", "A number as text."),
  f("str.length", [p("s")], "number", "Number of characters."),
  f("str.contains", [p("s"), p("part")], "bool", "True when s contains part."),

  // ---- arrays (also as methods: a.push(x))
  f("array.new", [p("size", "0"), p("init", "na")], "array", "A new list."),
  f("array.from", [], "array", "A list of the given values.", { variadic: true }),
  f("array.push", [p("id"), p("value")], "void", "Add to the end."),
  f("array.pop", [p("id")], "any", "Remove and return the last value."),
  f("array.shift", [p("id")], "any", "Remove and return the first value."),
  f("array.unshift", [p("id"), p("value")], "void", "Add to the start."),
  f("array.get", [p("id"), p("index")], "any", "Value at index (0 = first)."),
  f("array.set", [p("id"), p("index"), p("value")], "void", "Replace the value at index."),
  f("array.size", [p("id")], "number", "Number of values."),
  f("array.clear", [p("id")], "void", "Remove all values."),
  f("array.sum", [p("id")], "number", "Sum of the values."),
  f("array.avg", [p("id")], "number", "Mean of the values."),
  f("array.min", [p("id")], "number", "Smallest value."),
  f("array.max", [p("id")], "number", "Largest value."),
  f("array.includes", [p("id"), p("value")], "bool", "True when the value is in the list."),
  f("array.indexof", [p("id"), p("value")], "number", "First index of the value, -1 if absent."),
  f("array.sort", [p("id"), p("descending", "false")], "void", "Sort in place."),
  f("array.reverse", [p("id")], "void", "Reverse in place."),

  // ---- maps (also as methods: m.put(k, v))
  f("map.new", [], "map", "A new key to value map."),
  f("map.put", [p("id"), p("key"), p("value")], "void", "Set a key."),
  f("map.get", [p("id"), p("key")], "any", "Value for a key (na when missing)."),
  f("map.contains", [p("id"), p("key")], "bool", "True when the key is set."),
  f("map.remove", [p("id"), p("key")], "void", "Remove a key."),
  f("map.size", [p("id")], "number", "Number of keys."),
  f("map.keys", [p("id")], "array", "The keys as a list."),
  f("map.values", [p("id")], "array", "The values as a list."),
];

/** Built-ins by name. `na` appears twice (value and function): the function form wins here; the checker handles both. */
export const BY_NAME: Map<string, Builtin> = new Map(BUILTINS.map((b) => [b.name, b]));

/** Methods: `a.push(x)` = `array.push(a, x)`; `m.put(k, v)` = `map.put(m, k, v)`; `h.delete()` = `label|line|box.delete(h)`. */
export const METHOD_NAMESPACES = ["array", "map", "label", "line", "box", "table"] as const;

/** Caps (spec 1.7). Both engines use these numbers; the Python port mirrors them (checked by test_ts_mirrors.py). */
export const LIMITS = {
  sourceChars: 20_000,
  nodes: 3_000,
  stepsPerRun: 5_000_000,
  stepsPerBar: 100_000,
  arrayElements: 100_000,
  mapEntries: 50_000,
  lookback: 5_000,
  outputs: 64,
  drawingsPerKind: 500,
  alerts: 500,
} as const;
