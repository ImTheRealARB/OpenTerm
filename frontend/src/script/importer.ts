/**
 * OpenTerm Script importer (spec: docs/specs/PHASE_25.md section 6).
 *
 * Takes an indicator written in the common chart-script syntax ("the source script") and rewrites it into OpenTerm Script.
 * It is a PURE text translator: no network, no DOM, no engine. The app compiles the result afterwards and shows the report.
 *
 * How it works (read this first, it is the whole design):
 *   1. TOKENIZE every physical line. A token is whitespace, a comment, a string, a number, a colour, a (dotted) name or an
 *      operator. Strings and comments are tokens, so text such as "strategy.entry" inside a string is never treated as code.
 *   2. GROUP physical lines into STATEMENTS. A statement can span several lines (open brackets, or a line that ends with an
 *      operator or comma).
 *   3. TRANSLATE each statement token by token: rename what has a new name, remove what OpenTerm does not have (with a note),
 *      or DROP the whole statement (with a note). Calls to OpenTerm built-ins are checked against `names.ts` (BY_NAME).
 *   4. A dropped statement also drops its indented block, and every later statement that uses a variable it declared.
 *   5. Collect one report row per non-blank input line.
 *
 * Never write the other platform's name here: screen text and files call it "the source script".
 */
import { BY_NAME, SOURCES, type Param } from "./names";

// ---------------------------------------------------------------------------------------------------------------------
// Public types

export type ReportStatus = "ok" | "changed" | "dropped";

export interface ReportRow {
  /** 1-based line in the INPUT. */
  line: number;
  /** The input line, trimmed. */
  text: string;
  status: ReportStatus;
  /** Short plain note for the user. Empty when nothing needs saying. */
  note: string;
}

export interface ImportResult {
  source: string;
  report: ReportRow[];
}

// ---------------------------------------------------------------------------------------------------------------------
// Tables (the "knowledge" of the translator lives here, the code below only applies it)

/** Words with a meaning of their own: never treated as a variable or a function name. */
const KEYWORDS = new Set([
  "if", "else", "for", "to", "by", "while", "break", "continue", "var", "varip", "and", "or", "not", "true", "false", "na",
]);

/** First words of a name that belong to a built-in namespace. An unknown member of one of these is "not supported". */
const NAMESPACES = new Set([
  "ta", "math", "input", "color", "str", "array", "map", "label", "line", "box", "table", "request", "barstate", "syminfo",
  "timeframe", "strategy", "session", "chart", "ticker", "log", "runtime", "matrix", "linefill", "polyline", "plot", "hline",
  "shape", "location", "position", "size", "text", "extend", "xloc", "yloc", "display", "format", "scale", "order", "alert",
  "currency", "font", "adjustment", "backadjustment", "barmerge", "dayofweek", "earnings", "dividends", "splits",
]);

/** Constants of the source script that become a plain text value in OpenTerm Script. */
const CONST_MAP: Record<string, string> = {
  "plot.style_line": "line",
  "plot.style_stepline": "stepline",
  "plot.style_histogram": "histogram",
  "plot.style_columns": "columns",
  "plot.style_circles": "circles",
  "plot.style_area": "area",
  "shape.triangleup": "triangleup",
  "shape.triangledown": "triangledown",
  "shape.circle": "circle",
  "shape.cross": "cross",
  "shape.diamond": "diamond",
  "shape.arrowup": "arrowup",
  "shape.arrowdown": "arrowdown",
  "shape.labelup": "labelup",
  "shape.labeldown": "labeldown",
  "location.abovebar": "abovebar",
  "location.belowbar": "belowbar",
  "location.absolute": "absolute",
  "position.top_left": "top_left",
  "position.top_right": "top_right",
  "position.bottom_left": "bottom_left",
  "position.bottom_right": "bottom_right",
  "hline.style_solid": "solid",
  "hline.style_dashed": "dashed",
  "hline.style_dotted": "dotted",
  "label.style_label_down": "label_down",
  "label.style_label_up": "label_up",
};

/** A call that simply has a new name in OpenTerm Script. */
const RENAME_CALL: Record<string, string> = {
  study: "indicator",
  "request.security": "request",
  "input.integer": "input.int",
  "input.resolution": "input.timeframe",
  "array.new_float": "array.new",
  "array.new_int": "array.new",
  "array.new_bool": "array.new",
  "array.new_string": "array.new",
  "array.new_color": "array.new",
};

/** Old style names written without their namespace (`sma(close, 14)`). Only used when the script did not define that name. */
const LEGACY_CALL: Record<string, string> = {
  ...Object.fromEntries(
    [
      "sma", "ema", "wma", "rma", "vwma", "rsi", "stdev", "variance", "highest", "lowest", "change", "mom", "roc", "cum", "atr",
      "crossover", "crossunder", "cross", "rising", "falling", "barssince", "valuewhen", "linreg",
    ].map((n) => [n, `ta.${n}`]),
  ),
  ...Object.fromEntries(
    ["abs", "ceil", "floor", "round", "sqrt", "pow", "exp", "log", "log10", "max", "min", "avg", "sign"].map((n) => [n, `math.${n}`]),
  ),
  tostring: "str.tostring",
  security: "request",
};

/** Bare calls of the source script that OpenTerm does not have. */
const UNSUPPORTED_CALLS = new Set(["plotchar", "plotcandle", "plotbar", "plotarrow", "barcolor", "max_bars_back", "fixnan"]);

/** Bare names (no call) of the source script that OpenTerm does not have. */
const UNSUPPORTED_GLOBALS = new Set([
  "hlcc4", "year", "month", "weekofyear", "dayofmonth", "dayofweek", "hour", "minute", "second", "timenow", "time_close",
  "time_tradingday", "last_bar_time",
]);

/**
 * Positional order of the SOURCE script's parameters, when it differs from (or is longer than) OpenTerm's. A positional
 * argument takes its name from this list, and is then kept or dropped by name, like a named argument.
 */
const COMMON: Record<string, string[]> = {
  indicator: [
    "title", "shorttitle", "overlay", "format", "precision", "scale", "max_bars_back", "timeframe", "timeframe_gaps",
    "explicit_plot_zorder", "max_lines_count", "max_labels_count", "max_boxes_count",
  ],
  "input.int": ["defval", "title", "minval", "maxval", "step", "tooltip", "inline", "group", "confirm"],
  "input.float": ["defval", "title", "minval", "maxval", "step", "tooltip", "inline", "group", "confirm"],
  "input.bool": ["defval", "title", "tooltip", "inline", "group", "confirm"],
  "input.string": ["defval", "title", "options", "tooltip", "inline", "group", "confirm"],
  "input.source": ["defval", "title", "tooltip", "inline", "group", "confirm"],
  "input.symbol": ["defval", "title", "tooltip", "inline", "group", "confirm"],
  "input.timeframe": ["defval", "title", "options", "tooltip", "inline", "group", "confirm"],
  request: ["symbol", "timeframe", "expression", "gaps", "lookahead", "ignore_invalid_symbol", "currency"],
  plot: [
    "series", "title", "color", "linewidth", "style", "trackprice", "histbase", "offset", "join", "editable", "show_last",
    "display", "format", "precision", "force_overlay",
  ],
  hline: ["price", "title", "color", "linestyle", "linewidth", "editable", "display"],
  fill: ["plot1", "plot2", "color", "title", "editable", "show_last", "fillgaps", "display"],
  bgcolor: ["color", "offset", "editable", "show_last", "title", "display", "force_overlay"],
  plotshape: [
    "series", "title", "style", "location", "color", "offset", "text", "textcolor", "editable", "size", "show_last", "display",
    "format", "precision", "force_overlay",
  ],
  "label.new": [
    "x", "y", "text", "xloc", "yloc", "color", "style", "textcolor", "size", "textalign", "tooltip", "text_font_family",
    "force_overlay",
  ],
  "line.new": ["x1", "y1", "x2", "y2", "xloc", "extend", "color", "style", "width", "force_overlay"],
  "box.new": [
    "left", "top", "right", "bottom", "border_color", "border_width", "border_style", "extend", "xloc", "bgcolor", "text",
  ],
  "table.new": ["position", "columns", "rows", "bgcolor", "frame_color", "frame_width", "border_color", "border_width"],
  "table.cell": [
    "table_id", "column", "row", "text", "width", "height", "text_color", "text_halign", "text_valign", "text_size", "bgcolor",
    "tooltip",
  ],
  alert: ["message", "freq"],
  alertcondition: ["condition", "title", "message"],
  "str.tostring": ["value", "format"],
  nz: ["source", "replacement"],
};

/** Positional order of the OLD untyped `input(...)`. */
const COMMON_OLD_INPUT = ["defval", "title", "type", "minval", "maxval", "step", "options", "group", "tooltip", "inline", "confirm"];

/** Parameter names that are spelled differently in OpenTerm Script, per function. Tried before GLOBAL_RENAME. */
const FN_RENAME: Record<string, Record<string, string>> = {
  plotshape: { series: "cond" },
  "box.new": { border_color: "color" },
  "table.cell": { table_id: "id", text_color: "color" },
  "str.tostring": { value: "x" },
  nz: { source: "x", replacement: "y" },
  indicator: { max_labels_count: "max_labels" },
};

/** Parameter names that are spelled differently everywhere (used only when the name is not already a parameter). */
const GLOBAL_RENAME: Record<string, string> = {
  source: "src",
  series: "src",
  condition: "cond",
  minval: "min",
  maxval: "max",
  expression: "expr",
  fastlen: "fast",
  slowlen: "slow",
  siglen: "signal",
  source1: "a",
  source2: "b",
};

/** Words that start a declaration type (`float x = 1`). They are removed. */
const TYPE_WORDS = new Set(["int", "float", "bool", "string", "color", "label", "line", "box", "table", "linefill", "array", "map", "matrix"]);
const QUALIFIERS = new Set(["series", "simple", "const"]);

const ASSIGN_OPS = new Set(["=", ":=", "+=", "-=", "*=", "/=", "%="]);

/** A line that ends with one of these continues on the next line. */
const CONTINUE_END = new Set(["+", "-", "*", "/", "%", "==", "!=", "<", "<=", ">", ">=", "?", ":", ",", "=", ":=", "+=", "-=", "*=", "/=", "%="]);
/** A line that starts with one of these continues the line above. */
const CONTINUE_START = new Set(["and", "or", "?", ":", "+", "*", "/", "%", "==", "!=", "<", "<=", ">", ">="]);

// ---------------------------------------------------------------------------------------------------------------------
// Tokenizer

type Kind = "ws" | "comment" | "str" | "num" | "color" | "id" | "op";
interface Tok {
  k: Kind;
  s: string;
}

// Sticky regexes (flag y) match exactly at `lastIndex`, which is how the hand-written scanner below uses them.
const RE_WS = /[ \t]+/y;
const RE_ID = /[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*/y;
const RE_NUM = /(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?/y;
const RE_COLOR = /#[0-9a-fA-F]{3,8}/y;
const TWO_CHAR_OPS = new Set([":=", "==", "!=", "<=", ">=", "=>", "+=", "-=", "*=", "/=", "%="]);

function matchAt(re: RegExp, s: string, i: number): string | null {
  re.lastIndex = i;
  const m = re.exec(s);
  return m ? m[0] : null;
}

/** Split ONE physical line into tokens. Concatenating the token texts gives the line back exactly. */
function tokenize(line: string): Tok[] {
  const out: Tok[] = [];
  let i = 0;
  while (i < line.length) {
    const c = line[i];
    const ws = matchAt(RE_WS, line, i);
    if (ws) {
      out.push({ k: "ws", s: ws });
      i += ws.length;
    } else if (c === "/" && line[i + 1] === "/") {
      out.push({ k: "comment", s: line.slice(i) });
      i = line.length;
    } else if (c === '"' || c === "'") {
      // A string runs to the closing quote (backslash escapes the next character) or to the end of the line.
      let j = i + 1;
      while (j < line.length && line[j] !== c) j += line[j] === "\\" ? 2 : 1;
      j = Math.min(j + 1, line.length);
      out.push({ k: "str", s: line.slice(i, j) });
      i = j;
    } else if (c === "#" && matchAt(RE_COLOR, line, i)) {
      const m = matchAt(RE_COLOR, line, i) as string;
      out.push({ k: "color", s: m });
      i += m.length;
    } else if (matchAt(RE_ID, line, i)) {
      const m = matchAt(RE_ID, line, i) as string;
      out.push({ k: "id", s: m });
      i += m.length;
    } else if (matchAt(RE_NUM, line, i)) {
      const m = matchAt(RE_NUM, line, i) as string;
      out.push({ k: "num", s: m });
      i += m.length;
    } else {
      const two = line.slice(i, i + 2);
      const s = TWO_CHAR_OPS.has(two) ? two : (c as string);
      out.push({ k: "op", s });
      i += s.length;
    }
  }
  return out;
}

const isSig = (t: Tok): boolean => t.k !== "ws" && t.k !== "comment";
const sigIndexes = (toks: Tok[]): number[] => toks.flatMap((t, i) => (isSig(t) ? [i] : []));
const isOp = (t: Tok | undefined, s: string): boolean => !!t && t.k === "op" && t.s === s;

function lastSig(toks: Tok[]): Tok | undefined {
  for (let i = toks.length - 1; i >= 0; i--) if (isSig(toks[i])) return toks[i];
  return undefined;
}

/** Index of the next significant token at or after `from`, or -1. */
function nextSig(toks: Tok[], from: number): number {
  for (let i = from; i < toks.length; i++) if (isSig(toks[i])) return i;
  return -1;
}

const OPEN = "([{";
const CLOSE = ")]}";

/** Index of the bracket that closes the one at `open`, or -1. */
function matchBracket(toks: Tok[], open: number): number {
  let depth = 0;
  for (let i = open; i < toks.length; i++) {
    const t = toks[i];
    if (t.k !== "op") continue;
    if (OPEN.includes(t.s)) depth++;
    else if (CLOSE.includes(t.s) && --depth === 0) return i;
  }
  return -1;
}

/** Index of the `>` that closes the `<` at `open` (type lists such as `array.new<float>`), or -1. */
function matchAngle(toks: Tok[], open: number): number {
  let depth = 0;
  for (let i = open; i < toks.length; i++) {
    const t = toks[i];
    if (t.k === "op" && t.s === "<") depth++;
    else if (t.k === "op" && t.s === ">" && --depth === 0) return i;
    else if (t.k === "op" && !["<", ">", ","].includes(t.s)) return -1; // not a type list
  }
  return -1;
}

/** Split the tokens between ( ) at the commas that are not inside deeper brackets. */
function splitArgs(inner: Tok[]): Tok[][] {
  const parts: Tok[][] = [[]];
  let depth = 0;
  for (const t of inner) {
    if (t.k === "op") {
      if (OPEN.includes(t.s)) depth++;
      else if (CLOSE.includes(t.s)) depth--;
      else if (t.s === "," && depth === 0) {
        parts.push([]);
        continue;
      }
    }
    parts[parts.length - 1].push(t);
  }
  // `f()` has no arguments (not one empty one).
  if (parts.length === 1 && parts[0].every((t) => !isSig(t))) return [];
  return parts;
}

// ---------------------------------------------------------------------------------------------------------------------
// Context: what one statement collects while it is translated

type DropKind = "const" | "other";
interface Drop {
  kind: DropKind;
  msg: string;
}

interface State {
  /** Names the script defines itself (variables, functions, parameters): never renamed or treated as built-ins. */
  userNames: Set<string>;
  /** Names declared by lines we dropped: later lines that use them are dropped too. */
  dropped: Set<string>;
}

interface Ctx {
  st: State;
  notes: string[];
  changed: boolean;
  drop: Drop | null;
}

function newCtx(st: State): Ctx {
  return { st, notes: [], changed: false, drop: null };
}

/** Record a change (and optionally say why). */
function mark(ctx: Ctx, note?: string): void {
  ctx.changed = true;
  if (note && !ctx.notes.includes(note)) ctx.notes.push(note);
}

/** Ask for the statement (or, for a "const" drop, just the argument holding it) to be dropped. First reason wins; "other" beats "const". */
function setDrop(ctx: Ctx, kind: DropKind, msg: string): void {
  if (!ctx.drop || (ctx.drop.kind === "const" && kind === "other")) ctx.drop = { kind, msg };
}

const str = (s: string): Tok => ({ k: "str", s: JSON.stringify(s) });
const op = (s: string): Tok => ({ k: "op", s });
const id = (s: string): Tok => ({ k: "id", s });
const text = (toks: Tok[]): string => toks.map((t) => t.s).join("");

// ---------------------------------------------------------------------------------------------------------------------
// Call arguments

interface Arg {
  /** Everything before the value: leading space, `name`, `=`. */
  prefix: Tok[];
  name?: string;
  /** From the first to the last significant token of the value (empty for a trailing comma). */
  value: Tok[];
  /** Whitespace and comments after the value. */
  suffix: Tok[];
}

function parseArg(seg: Tok[]): Arg {
  const sig = sigIndexes(seg);
  let valueFrom = sig.length ? sig[0] : seg.length;
  let name: string | undefined;
  if (sig.length >= 2 && seg[sig[0]].k === "id" && !seg[sig[0]].s.includes(".") && isOp(seg[sig[1]], "=")) {
    name = seg[sig[0]].s;
    valueFrom = sig.length > 2 ? sig[2] : seg.length;
  }
  const valueTo = sig.length && valueFrom < seg.length ? sig[sig.length - 1] + 1 : valueFrom;
  return { prefix: seg.slice(0, valueFrom), name, value: seg.slice(valueFrom, valueTo), suffix: seg.slice(valueTo) };
}

/** Which OpenTerm function does the old untyped `input(...)` stand for? Looks at `type=` first, then at the default value. */
function inferInput(args: Arg[]): string | null {
  const byName = (n: string) => args.find((a) => a.name === n)?.value;
  const positional = args.filter((a) => a.name === undefined);
  const typeArg = byName("type") ?? positional[2]?.value;
  const typeTxt = typeArg ? text(typeArg).trim() : "";
  const FROM_TYPE: Record<string, string> = {
    "input.integer": "input.int",
    "input.int": "input.int",
    "input.float": "input.float",
    "input.bool": "input.bool",
    "input.string": "input.string",
    "input.source": "input.source",
    "input.resolution": "input.timeframe",
    "input.timeframe": "input.timeframe",
  };
  if (FROM_TYPE[typeTxt]) return FROM_TYPE[typeTxt];
  const def = (byName("defval") ?? positional[0]?.value);
  const d = def ? text(def).trim() : "";
  if (/^-?\d+$/.test(d)) return "input.int";
  if (/^-?(\d+\.\d*|\.\d+|\d+(\.\d*)?[eE][+-]?\d+)$/.test(d)) return "input.float";
  if (d === "true" || d === "false") return "input.bool";
  if (/^["']/.test(d)) return "input.string";
  if ((SOURCES as readonly string[]).includes(d)) return "input.source";
  return null;
}

/** Pick the OpenTerm parameter that an argument name stands for. Returns null when OpenTerm has no such parameter. */
function resolveParam(fn: string, given: string, names: string[]): { ours: string; renamed: boolean } | null {
  if (names.includes(given)) return { ours: given, renamed: false };
  const to = FN_RENAME[fn]?.[given] ?? GLOBAL_RENAME[given];
  if (to && names.includes(to)) return { ours: to, renamed: true };
  return null;
}

interface Kept {
  ours: string;
  positional: boolean;
  value: Tok[];
  /** Index of the parameter in OpenTerm's list (-1 for the extra values of a variadic call). */
  paramIndex: number;
}

/**
 * Translate one call. `i` = index of the name token, `afterName` = first token after the name (and after any `<type list>`),
 * `open` = index of the `(`. Returns the new tokens and the index after the closing `)`.
 */
function handleCall(toks: Tok[], i: number, afterName: number, open: number, name: string, ctx: Ctx): { out: Tok[]; next: number } {
  const close = matchBracket(toks, open);
  if (close === -1) return { out: toks.slice(i), next: toks.length }; // unbalanced: leave the rest alone, the compiler will say so
  const raw = (): { out: Tok[]; next: number } => ({ out: toks.slice(i, close + 1), next: close + 1 });
  const gap = toks.slice(afterName, open);
  const args = splitArgs(toks.slice(open + 1, close)).map(parseArg);
  const firstSeg = name.split(".")[0];
  const dotted = name.includes(".");
  const userOwned = ctx.st.userNames.has(dotted ? firstSeg : name);

  // ----- 1. which OpenTerm name is this call?
  let canonical = name;
  let oldInput = false;
  if (!userOwned) {
    if (name === "input") {
      oldInput = true;
      const inferred = inferInput(args);
      if (!inferred) {
        setDrop(ctx, "other", "input: the type of this setting cannot be told from its default value");
        return raw();
      }
      canonical = inferred;
      mark(ctx, `input is now ${canonical}`);
    } else if (RENAME_CALL[name]) {
      canonical = RENAME_CALL[name];
      mark(ctx, `${name} is now ${canonical}`);
    } else if (!dotted && LEGACY_CALL[name]) {
      canonical = LEGACY_CALL[name];
      mark(ctx, `old name ${name} is now ${canonical}`);
    }
  }
  const info = BY_NAME.get(canonical);

  // ----- 2. calls that are not OpenTerm built-ins
  if (!info) {
    if (!userOwned && dotted && NAMESPACES.has(firstSeg)) {
      setDrop(ctx, "other", `${name} is not supported`);
      return raw();
    }
    if (!userOwned && !dotted && (name === "strategy" || name === "library")) {
      setDrop(ctx, "other", `${name} is not supported`);
      return raw();
    }
    if (!userOwned && !dotted && UNSUPPORTED_CALLS.has(name)) {
      setDrop(ctx, "other", `${name} is not supported`);
      return raw();
    }
    if (ctx.st.dropped.has(dotted ? firstSeg : name)) {
      setDrop(ctx, "other", `uses ${dotted ? firstSeg : name} (dropped above)`);
      return raw();
    }
    // A function or method the script defines itself: keep its arguments, only translate what is inside them.
    const body: Tok[] = [];
    args.forEach((a, n) => {
      if (n > 0) body.push(op(","));
      body.push(...a.prefix, ...rewriteRange(a.value, ctx), ...a.suffix);
    });
    return { out: [id(canonical), ...gap, op("("), ...body, op(")")], next: close + 1 };
  }

  // ----- 3. an OpenTerm built-in: check every argument against its parameter list
  const params: Param[] = info.params ?? [];
  const names = params.map((p) => p.name);
  const order = oldInput ? COMMON_OLD_INPUT : (COMMON[canonical] ?? names);
  const silentDrop = oldInput ? new Set(["type"]) : new Set<string>();
  const kept: Kept[] = [];
  let structural = canonical !== name; // true once the argument list can no longer be copied as it is
  let positionalSeen = 0;
  const rewrittenValues = new Map<Arg, Tok[]>();

  for (const a of args) {
    // Work out the parameter this argument is for.
    let given: string | undefined = a.name;
    let extraVariadic = false;
    if (given === undefined) {
      const n = positionalSeen++;
      if (info.variadic && n >= names.length) extraVariadic = true;
      else given = order[n];
    }
    // Translate the value in its own context so that a dropped argument leaves no notes behind.
    const child = newCtx(ctx.st);
    const value = rewriteRange(a.value, child);
    rewrittenValues.set(a, value);

    if (extraVariadic) {
      kept.push({ ours: "", positional: true, value, paramIndex: -1 });
      mergeChild(ctx, child);
      continue;
    }
    if (given === undefined) {
      structural = true;
      mark(ctx, `${canonical}: extra argument dropped (not supported)`);
      continue;
    }
    const hit = info.variadic && a.name === undefined ? { ours: given, renamed: false } : resolveParam(canonical, given, names);
    if (!hit) {
      structural = true;
      if (!silentDrop.has(given)) mark(ctx, `${canonical}: ${given} is not supported, dropped`);
      else mark(ctx);
      continue;
    }
    const paramIndex = names.indexOf(hit.ours);
    if (child.drop?.kind === "const") {
      // The value is a constant OpenTerm does not have. A parameter with a default can go; a required one cannot.
      if (paramIndex >= 0 && params[paramIndex].def === undefined) setDrop(ctx, "other", child.drop.msg);
      else {
        structural = true;
        mark(ctx, `${canonical}: ${child.drop.msg}, argument ${hit.ours} dropped`);
      }
      continue;
    }
    if (child.drop) setDrop(ctx, child.drop.kind, child.drop.msg);
    mergeChild(ctx, child);
    if (hit.renamed) {
      structural = true;
      if (a.name !== undefined) mark(ctx, `${canonical}: ${given} is now ${hit.ours}`);
    }
    let v = value;
    // A list written with [ ] is passed to OpenTerm as array.from(...).
    if (hit.ours === "options" && v.length >= 2 && isOp(v[0], "[") && isOp(v[v.length - 1], "]")) {
      v = [id("array.from"), op("("), ...v.slice(1, -1), op(")")];
      structural = true;
      mark(ctx, "options: list written as array.from");
    }
    kept.push({ ours: hit.ours, positional: a.name === undefined, value: v, paramIndex });
  }

  // ----- 4. write the call back
  const nameTok = id(canonical);
  if (!structural) {
    const body: Tok[] = [];
    args.forEach((a, n) => {
      if (n > 0) body.push(op(","));
      body.push(...a.prefix, ...(rewrittenValues.get(a) ?? a.value), ...a.suffix);
    });
    return { out: [nameTok, ...gap, op("("), ...body, op(")")], next: close + 1 };
  }
  // Rebuilt: keep an argument positional only while the positional ones still line up with OpenTerm's parameter order.
  const parts: string[] = [];
  let nextParam = 0;
  let stillPositional = true;
  for (const k of kept) {
    const v = text(k.value).trim();
    if (k.positional && (k.paramIndex === -1 || (stillPositional && k.paramIndex === nextParam))) {
      parts.push(v);
      if (k.paramIndex !== -1) nextParam++;
    } else {
      stillPositional = false;
      parts.push(`${k.ours}=${v}`);
    }
  }
  return { out: [nameTok, ...gap, op("("), op(parts.join(", ")), op(")")], next: close + 1 };
}

/** Take over what a finished argument translation found. */
function mergeChild(ctx: Ctx, child: Ctx): void {
  if (child.changed) ctx.changed = true;
  for (const n of child.notes) if (!ctx.notes.includes(n)) ctx.notes.push(n);
}

// ---------------------------------------------------------------------------------------------------------------------
// Expression translation

/**
 * Translate a run of tokens that holds expressions (a right-hand side, a condition, a function body).
 * Looks at every name: constants become text, calls are checked and rewritten, unknown built-ins ask for a drop.
 */
function rewriteRange(toks: Tok[], ctx: Ctx): Tok[] {
  const out: Tok[] = [];
  let i = 0;
  while (i < toks.length) {
    const t = toks[i];
    if (t.k !== "id") {
      out.push(t);
      i++;
      continue;
    }
    // A name right after a "." is a member of something else (`x[1].y`): leave it.
    const prev = lastSig(out);
    if (isOp(prev, ".") || KEYWORDS.has(t.s)) {
      out.push(t);
      i++;
      continue;
    }
    const name = t.s;
    let j = i + 1;
    // `array.new<float>(...)`: drop the type list.
    if (/^(array|map)\.new$/.test(name) && isOp(toks[j], "<")) {
      const end = matchAngle(toks, j);
      if (end !== -1) {
        j = end + 1;
        mark(ctx, `${name}: type list removed`);
      }
    }
    const nx = nextSig(toks, j);
    if (nx !== -1 && isOp(toks[nx], "(")) {
      const r = handleCall(toks, i, j, nx, name, ctx);
      out.push(...r.out);
      i = r.next;
      continue;
    }
    out.push(...rewriteName(name, t, ctx));
    i = j;
  }
  return out;
}

/** A name that is NOT called: a variable, a constant or a built-in series. */
function rewriteName(name: string, t: Tok, ctx: Ctx): Tok[] {
  const dotted = name.includes(".");
  const first = name.split(".")[0];
  const userOwned = ctx.st.userNames.has(dotted ? first : name);

  if (CONST_MAP[name] !== undefined) {
    mark(ctx, `${name} is now "${CONST_MAP[name]}"`);
    return [str(CONST_MAP[name])];
  }
  if (name === "syminfo.tickerid") {
    mark(ctx, "syminfo.tickerid is now an empty text (the chart's own symbol)");
    return [str("")];
  }
  // The true range was a plain value in the source script; here it is a call.
  if (name === "ta.tr" || (name === "tr" && !userOwned)) {
    mark(ctx, `${name} is now ta.tr()`);
    return [id("ta.tr"), op("("), op(")")];
  }
  if (BY_NAME.has(name)) return [t];
  if (!userOwned && dotted && NAMESPACES.has(first)) {
    // `strategy.*` always drops the line; other unknown constants may only cost an argument.
    setDrop(ctx, first === "strategy" ? "other" : "const", `${name} is not supported`);
    return [t];
  }
  if (!userOwned && !dotted && UNSUPPORTED_GLOBALS.has(name)) {
    setDrop(ctx, "other", `${name} is not supported`);
    return [t];
  }
  if (ctx.st.dropped.has(first)) setDrop(ctx, "other", `uses ${first} (dropped above)`);
  return [t];
}

// ---------------------------------------------------------------------------------------------------------------------
// Statements

interface PLine {
  no: number;
  raw: string;
  indent: number;
  toks: Tok[];
  blank: boolean;
  commentOnly: boolean;
}

interface Unit {
  kind: "blank" | "comment" | "stmt";
  lines: PLine[];
}

function toPLine(raw: string, no: number): PLine {
  const toks = tokenize(raw);
  const sig = sigIndexes(toks);
  const lead = /^[ \t]*/.exec(raw)?.[0] ?? "";
  let indent = 0;
  for (const c of lead) indent += c === "\t" ? 4 : 1;
  return { no, raw, indent, toks, blank: raw.trim() === "", commentOnly: sig.length === 0 && raw.trim() !== "" };
}

/** Bracket depth change of one line. */
function depthChange(toks: Tok[]): number {
  let d = 0;
  for (const t of toks) {
    if (t.k !== "op") continue;
    if (OPEN.includes(t.s)) d++;
    else if (CLOSE.includes(t.s)) d--;
  }
  return d;
}

/** Group physical lines into blank lines, comment lines and statements (a statement may span lines). */
function groupLines(lines: PLine[]): Unit[] {
  const units: Unit[] = [];
  let cur: Unit | null = null;
  let depth = 0;
  let continues = false; // the last line of `cur` ends with an operator or comma
  for (const ln of lines) {
    if (ln.blank) {
      if (cur && depth > 0) cur.lines.push(ln);
      else units.push({ kind: "blank", lines: [ln] });
      continue;
    }
    const sig = ln.toks.filter(isSig);
    const startsWithContinuation = sig.length > 0 && CONTINUE_START.has(sig[0].s) && (sig[0].k === "op" || sig[0].s === "and" || sig[0].s === "or");
    const joins = cur !== null && (depth > 0 || continues || startsWithContinuation);
    if (ln.commentOnly && !joins) {
      units.push({ kind: "comment", lines: [ln] });
      continue;
    }
    if (joins && cur) cur.lines.push(ln);
    else {
      cur = { kind: "stmt", lines: [ln] };
      units.push(cur);
      depth = 0;
    }
    depth = Math.max(0, depth + depthChange(ln.toks));
    if (!ln.commentOnly) {
      const last = sig[sig.length - 1];
      continues = !!last && last.k === "op" && CONTINUE_END.has(last.s);
    }
  }
  return units;
}

/** All tokens of a statement, with a newline token between its physical lines. */
function joinTokens(lines: PLine[]): Tok[] {
  const out: Tok[] = [];
  lines.forEach((ln, n) => {
    if (n > 0) out.push({ k: "ws", s: "\n" });
    out.push(...ln.toks);
  });
  return out;
}

interface Head {
  kind: "decl" | "assign" | "func" | "other";
  /** Names declared (decl), assigned (assign) or defined (func: the function name). */
  names: string[];
  /** Token indexes to delete (type words). */
  remove: Set<number>;
  /** Token index of the `var` / `varip` word, or -1. */
  varIdx: number;
  /** Token index where the right-hand side (decl) or the body (func) starts; the head is everything before. */
  bodyFrom: number;
  /** Function parameters. */
  params: string[];
  /** Variable of a `for` loop. */
  forVar?: string;
}

/** Look at the start of a statement: is it a declaration, a reassignment, a function definition or something else? */
function analyzeHead(toks: Tok[]): Head {
  const head: Head = { kind: "other", names: [], remove: new Set(), varIdx: -1, bodyFrom: 0, params: [] };
  const S = sigIndexes(toks);
  if (S.length === 0) return head;
  const w0 = toks[S[0]];

  if (w0.k === "id" && w0.s === "for" && S[1] !== undefined && toks[S[1]].k === "id") head.forVar = toks[S[1]].s;

  // Tuple declaration: [a, b] = ...
  if (isOp(w0, "[")) {
    const close = matchBracket(toks, S[0]);
    const after = close === -1 ? -1 : nextSig(toks, close + 1);
    if (after !== -1 && isOp(toks[after], "=")) {
      head.kind = "decl";
      head.names = toks.slice(S[0], close).filter((x) => x.k === "id").map((x) => x.s);
      head.bodyFrom = after + 1;
    }
    return head;
  }

  // Declaration or reassignment, with an optional `var`, qualifier and type: `var float x = 1`
  const tryFrom = (consumeType: boolean): boolean => {
    let p = 0;
    if (w0.k === "id" && (w0.s === "var" || w0.s === "varip")) {
      head.varIdx = S[0];
      p = 1;
    }
    const typeStart = p;
    if (consumeType) {
      while (S[p] !== undefined && QUALIFIERS.has(toks[S[p]].s)) p++;
      if (S[p] !== undefined && TYPE_WORDS.has(toks[S[p]].s) && toks[S[p]].k === "id") {
        p++;
        if (S[p] !== undefined && isOp(toks[S[p]], "<")) {
          const end = matchAngle(toks, S[p]);
          if (end === -1) return false;
          while (S[p] !== undefined && S[p] <= end) p++;
        }
      }
    }
    const nameTok = S[p] !== undefined ? toks[S[p]] : undefined;
    const opTok = S[p + 1] !== undefined ? toks[S[p + 1]] : undefined;
    if (!nameTok || nameTok.k !== "id" || KEYWORDS.has(nameTok.s) || nameTok.s.includes(".")) return false;
    if (!opTok || opTok.k !== "op" || !ASSIGN_OPS.has(opTok.s)) return false;
    head.kind = opTok.s === "=" ? "decl" : "assign";
    head.names = [nameTok.s];
    head.bodyFrom = S[p + 1] + 1;
    if (p > typeStart) for (let q = S[typeStart]; q < S[p]; q++) head.remove.add(q);
    return true;
  };
  if (tryFrom(true) || tryFrom(false)) return head;
  head.varIdx = -1;
  head.remove.clear();

  // Function definition: name(params) =>
  if (w0.k === "id" && !KEYWORDS.has(w0.s) && !w0.s.includes(".") && S[1] !== undefined && isOp(toks[S[1]], "(")) {
    const close = matchBracket(toks, S[1]);
    const after = close === -1 ? -1 : nextSig(toks, close + 1);
    if (after !== -1 && isOp(toks[after], "=>")) {
      head.kind = "func";
      head.names = [w0.s];
      head.bodyFrom = after + 1;
      // Parameters: drop type words in front of a name (`float x`), remember the names.
      const inner = toks.slice(S[1] + 1, close);
      let pos = S[1] + 1;
      for (const seg of splitArgs(inner)) {
        const segSig = sigIndexes(seg);
        const eq = segSig.findIndex((q) => isOp(seg[q], "="));
        const before = eq === -1 ? segSig : segSig.slice(0, eq);
        if (before.length > 0) {
          const nameIdx = before[before.length - 1];
          if (seg[nameIdx].k === "id") head.params.push(seg[nameIdx].s);
          if (before.length > 1) for (let q = before[0]; q < nameIdx; q++) head.remove.add(pos + q);
        }
        pos += seg.length + 1; // +1 for the comma
      }
    }
  }
  return head;
}

interface StmtResult {
  text: string | null;
  dropped: boolean;
  changed: boolean;
  notes: string[];
  /** Names this statement declares (used when it is dropped). */
  declares: string[];
  /** "if" for `if` and `else if`, "else" for a plain `else`. */
  chain: "if" | "else" | null;
  /** Block header kind (the next, deeper lines belong to it). */
  header: "if" | "loop" | "function" | null;
}

function dropResult(msg: string, declares: string[], chain: StmtResult["chain"]): StmtResult {
  return { text: null, dropped: true, changed: false, notes: [msg], declares, chain, header: null };
}

/** Statements that are dropped whatever they contain. Returns the note, or null. */
function hardDrop(toks: Tok[]): string | null {
  const S = sigIndexes(toks);
  if (S.length === 0) return null;
  const w0 = toks[S[0]];
  const w1 = S[1] !== undefined ? toks[S[1]] : undefined;
  if (w0.k === "id") {
    if (["import", "export", "method", "enum"].includes(w0.s)) return `${w0.s} is not supported`;
    if (w0.s === "type" && w1 && w1.k === "id") return "type is not supported";
    if ((w0.s === "strategy" || w0.s === "library") && isOp(w1, "(")) return `${w0.s} is not supported`;
    if (w0.s === "for" && toks.some((t) => t.k === "id" && t.s === "in")) return "for ... in is not supported";
  }
  if (toks.some((t) => t.k === "id" && t.s === "switch")) return "switch is not supported: block dropped";
  return null;
}

/** Collect the names a script defines itself. Done before translating, so `max(a, b)` is left alone when the script has its own `max`. */
function collectUserNames(units: Unit[]): Set<string> {
  const names = new Set<string>();
  for (const u of units) {
    if (u.kind !== "stmt") continue;
    const h = analyzeHead(joinTokens(u.lines));
    h.names.forEach((n) => names.add(n));
    h.params.forEach((n) => names.add(n));
    if (h.forVar) names.add(h.forVar);
  }
  return names;
}

function processStmt(unit: Unit, st: State): StmtResult {
  const toks = joinTokens(unit.lines);
  const S = sigIndexes(toks);
  const w0 = toks[S[0]];
  const w1 = S[1] !== undefined ? toks[S[1]] : undefined;
  const head = analyzeHead(toks);
  const chain: StmtResult["chain"] = w0.s === "if" ? "if" : w0.s === "else" ? (w1 && w1.s === "if" ? "if" : "else") : null;

  const hard = hardDrop(toks);
  if (hard) return dropResult(hard, head.kind === "decl" || head.kind === "func" ? head.names : [], chain);

  const ctx = newCtx(st);
  let result: Tok[];

  if (head.kind === "decl" || head.kind === "func") {
    const front = toks.slice(0, head.bodyFrom).map((t, n) => (head.remove.has(n) ? null : t));
    if (head.remove.size > 0) mark(ctx, head.kind === "func" ? "parameter types removed" : "type word removed");
    if (head.varIdx >= 0 && toks[head.varIdx].s === "varip") {
      front[head.varIdx] = { k: "id", s: "var" };
      mark(ctx, "varip is now var");
    }
    // The declared name itself is not a "use": translate only what comes after the = (or =>).
    const body = rewriteRange(toks.slice(head.bodyFrom), ctx);
    result = [...(front.filter((t) => t !== null) as Tok[]), ...body];
  } else {
    // Reassignments, headers (`if`, `for ...`), calls: translate everything.
    result = rewriteRange(toks, ctx);
  }

  if (ctx.drop) {
    return dropResult(ctx.drop.msg, head.kind === "decl" || head.kind === "func" ? head.names : [], chain);
  }

  // A kept declaration defines the name again: later lines may use it.
  if (head.kind === "decl" || head.kind === "func") head.names.forEach((n) => st.dropped.delete(n));

  const last = lastSig(result);
  const header: StmtResult["header"] =
    head.kind === "func" && isOp(last, "=>") ? "function" : w0.s === "if" || w0.s === "else" ? "if" : w0.s === "for" || w0.s === "while" ? "loop" : null;
  return { text: text(result), dropped: false, changed: ctx.changed, notes: ctx.notes, declares: head.names, chain, header };
}

// ---------------------------------------------------------------------------------------------------------------------
// The driver

interface Open {
  indent: number;
  indentStr: string;
  outIndex: number;
  kind: "if" | "loop" | "function";
  hasBody: boolean;
  /** Names of the function (for a function header), to drop later uses when its whole body was dropped. */
  name?: string;
  rows: ReportRow[];
}

export function importScript(src: string): ImportResult {
  const rawLines = src.replace(/\r\n?/g, "\n").split("\n");
  // A trailing newline makes a last empty element: it is not a line.
  if (rawLines.length > 0 && rawLines[rawLines.length - 1] === "") rawLines.pop();
  const plines = rawLines.map((raw, n) => toPLine(raw, n + 1));
  const units = groupLines(plines);
  const st: State = { userNames: collectUserNames(units), dropped: new Set() };

  const out: (string | null)[] = [];
  const report: ReportRow[] = [];
  let dropIndent = -1; // >= 0 while inside the block of a dropped statement
  let dropChain = -1; // indent of a dropped `if` whose `else` lines must go too
  const stack: Open[] = [];
  let placeholders = 0;

  const rowsFor = (lines: PLine[], status: ReportStatus, note: string): ReportRow[] =>
    lines
      .filter((l) => !l.blank)
      .map((l, n) => ({
        line: l.no,
        text: l.raw.trim(),
        status,
        note: n === 0 ? note : status === "ok" ? "" : "part of the statement above",
      }));

  /** A header leaves the stack: if all its body was dropped, fix the hole so the result still parses. */
  const finalize = (o: Open): void => {
    if (o.hasBody) return;
    if (o.kind === "function") {
      out[o.outIndex] = null;
      if (o.name) st.dropped.add(o.name);
      for (const r of o.rows) {
        r.status = "dropped";
        r.note = r.note ? r.note : "every line of this function was dropped";
      }
      return;
    }
    placeholders++;
    out.splice(o.outIndex + 1, 0, `${o.indentStr}    _empty${placeholders} = na`);
    const row = o.rows[0];
    if (row) {
      if (row.status === "ok") row.status = "changed";
      row.note = [row.note, "every line inside was dropped: a placeholder line was added"].filter(Boolean).join("; ");
    }
  };

  for (const unit of units) {
    if (unit.kind === "blank") {
      out.push("");
      continue;
    }
    const ln = unit.lines[0];

    if (unit.kind === "comment") {
      if (/^\s*\/\/\s*@version\s*=/.test(ln.raw)) {
        report.push(...rowsFor(unit.lines, "dropped", "version line is not needed"));
      } else if (dropIndent >= 0 && ln.indent > dropIndent) {
        report.push(...rowsFor(unit.lines, "dropped", "inside a dropped block"));
      } else {
        report.push(...rowsFor(unit.lines, "ok", ""));
        out.push(ln.raw.replace(/\s+$/, ""));
      }
      continue;
    }

    // ----- a statement
    const indent = ln.indent;
    while (stack.length > 0 && stack[stack.length - 1].indent >= indent) finalize(stack.pop() as Open);

    if (dropIndent >= 0) {
      if (indent > dropIndent) {
        report.push(...rowsFor(unit.lines, "dropped", "inside a dropped block"));
        continue;
      }
      dropIndent = -1;
    }
    const firstWord = unit.lines[0].toks.find(isSig)?.s;
    if (dropChain >= 0) {
      if (indent === dropChain && firstWord === "else") {
        // The `else` of a dropped `if` has nothing to belong to. A plain `else` ends the chain.
        const second = unit.lines[0].toks.filter(isSig)[1]?.s;
        if (second !== "if") dropChain = -1;
        dropIndent = indent;
        report.push(...rowsFor(unit.lines, "dropped", "belongs to a dropped if"));
        continue;
      }
      dropChain = -1;
    }

    const res = processStmt(unit, st);
    if (res.dropped) {
      dropIndent = indent;
      if (res.chain === "if") dropChain = indent;
      res.declares.forEach((n) => st.dropped.add(n));
      report.push(...rowsFor(unit.lines, "dropped", res.notes[0] ?? ""));
      continue;
    }

    const rows = rowsFor(unit.lines, res.changed ? "changed" : "ok", res.notes.join("; "));
    report.push(...rows);
    out.push(res.text);
    if (stack.length > 0) stack[stack.length - 1].hasBody = true;
    if (res.header) {
      const lead = /^[ \t]*/.exec(ln.raw)?.[0] ?? "";
      const name = res.header === "function" ? res.declares[0] : undefined;
      stack.push({ indent, indentStr: lead, outIndex: out.length - 1, kind: res.header, hasBody: false, name, rows });
    }
  }
  while (stack.length > 0) finalize(stack.pop() as Open);

  // Tidy: no leading blank lines, at most one blank line in a row, exactly one newline at the end.
  const lines: string[] = [];
  for (const l of out) {
    if (l === null) continue;
    if (l === "" && (lines.length === 0 || lines[lines.length - 1] === "")) continue;
    lines.push(l);
  }
  while (lines.length > 0 && lines[lines.length - 1] === "") lines.pop();
  return { source: lines.join("\n") + "\n", report };
}
