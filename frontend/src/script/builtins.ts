/**
 * OpenTerm Script built-in functions that need no per-call-site state: math, text, colours, arrays, maps and drawings.
 * (`ta.*` is in ta.ts; plot / fill / alert / input / request need the compiler's output records and live in compile.ts.)
 *
 * Every function here has the shape `(ctx, args) => value`. `args` holds the already evaluated arguments in the order
 * of names.ts (defaults filled in), so a function never has to think about argument names or missing arguments.
 * A mistake in the script's data (an array index out of range, text where a number is needed) throws a
 * ScriptRuntimeError; the compiler adds the line and column of the call.
 */
import { LIMITS } from "./names";
import {
  ArrVal,
  BoxH,
  LabelH,
  LineH,
  MapVal,
  ScriptRuntimeError,
  TableH,
  colorNew,
  colorOrNull,
  colorRgb,
  fmtNum,
  typeName,
} from "./values";

/** What these functions need from the run: the memory counters and the live drawing lists. */
export interface BuiltinCtx {
  memArr: number;
  memMap: number;
  maxLabels: number;
  labels: LabelH[];
  lines: LineH[];
  boxes: BoxH[];
  tables: TableH[];
}

export type Impl = (c: BuiltinCtx, a: unknown[]) => unknown;

// ---------------------------------------------------------------- argument helpers

function bad(what: string, v: unknown): never {
  throw new ScriptRuntimeError(`EXPECTED ${what}, GOT ${typeName(v)}`);
}
export function num(v: unknown): number {
  return typeof v === "number" ? v : bad("A NUMBER", v);
}
function str(v: unknown): string {
  return typeof v === "string" ? v : bad("TEXT", v);
}
function arr(v: unknown): ArrVal {
  return v instanceof ArrVal ? v : bad("AN ARRAY", v);
}
function map(v: unknown): MapVal {
  return v instanceof MapVal ? v : bad("A MAP", v);
}
function label(v: unknown): LabelH {
  return v instanceof LabelH ? v : bad("A LABEL", v);
}
function line(v: unknown): LineH {
  return v instanceof LineH ? v : bad("A LINE", v);
}
function box(v: unknown): BoxH {
  return v instanceof BoxH ? v : bad("A BOX", v);
}
function table(v: unknown): TableH {
  return v instanceof TableH ? v : bad("A TABLE", v);
}
/** A whole number that is a valid index into a list of `len` items. */
function index(v: unknown, len: number): number {
  const i = num(v);
  if (i !== Math.floor(i) || i < 0 || i >= len) throw new ScriptRuntimeError(`INDEX ${i !== i ? "NA" : i} OUT OF RANGE (SIZE ${len})`);
  return i;
}
function key(v: unknown): string | number {
  if (typeof v === "string") return v;
  if (typeof v === "number" && v === v) return v;
  throw new ScriptRuntimeError("MAP KEYS MUST BE TEXT OR NUMBERS (NOT NA)");
}
/** Text for a message or label: numbers are written the short way. */
export function textOf(v: unknown): string {
  if (typeof v === "string") return v;
  if (typeof v === "number") return fmtNum(v, -1);
  return bad("TEXT", v);
}

function addArr(c: BuiltinCtx, k: number): void {
  c.memArr += k;
  if (c.memArr > LIMITS.arrayElements) throw new ScriptRuntimeError("MEMORY LIMIT (ARRAYS)");
}
function addMap(c: BuiltinCtx, k: number): void {
  c.memMap += k;
  if (c.memMap > LIMITS.mapEntries) throw new ScriptRuntimeError("MEMORY LIMIT (MAPS)");
}

/** Add a new drawing to its list and delete the oldest when there are too many. */
function keep<T extends { dead: boolean }>(list: T[], h: T, max: number): T {
  list.push(h);
  while (list.length > max) {
    const old = list.shift() as T;
    old.dead = true;
  }
  return h;
}
function drop<T extends { dead: boolean }>(list: T[], h: T): void {
  if (h.dead) return;
  h.dead = true;
  const i = list.indexOf(h);
  if (i >= 0) list.splice(i, 1);
}

// ---------------------------------------------------------------- math

export const MATH1: Record<string, (x: number) => number> = {
  "math.abs": Math.abs,
  "math.ceil": Math.ceil,
  "math.floor": Math.floor,
  "math.sqrt": (x) => (x >= 0 ? Math.sqrt(x) : NaN),
  "math.exp": Math.exp,
  "math.log": (x) => (x > 0 ? Math.log(x) : NaN),
  "math.log10": (x) => (x > 0 ? Math.log10(x) : NaN),
  "math.sign": (x) => (x > 0 ? 1 : x < 0 ? -1 : x === 0 ? 0 : NaN),
};

/** Round half away from zero to `digits` decimals. */
function round(x: number, digits: number): number {
  if (x !== x || digits !== digits) return NaN;
  const f = Math.pow(10, Math.floor(digits));
  const r = Math.round(Math.abs(x) * f) / f;
  return x < 0 ? -r : r;
}

function fold(a: unknown[], op: (acc: number, x: number) => number): number {
  let acc = num(a[0]);
  for (let i = 1; i < a.length; i++) {
    const x = num(a[i]);
    if (acc !== acc || x !== x) acc = NaN;
    else acc = op(acc, x);
  }
  return acc;
}

// ---------------------------------------------------------------- the table

export const FN: Record<string, Impl> = {
  nz: (_c, a) => (typeof a[0] === "number" && a[0] !== a[0] ? a[1] : a[0]),
  na: (_c, a) => (typeof a[0] === "number" ? (a[0] !== a[0] ? 1 : 0) : a[0] === undefined || a[0] === null ? 1 : 0),

  "math.round": (_c, a) => round(num(a[0]), num(a[1])),
  "math.pow": (_c, a) => {
    const r = Math.pow(num(a[0]), num(a[1]));
    return Number.isFinite(r) ? r : NaN;
  },
  "math.max": (_c, a) => fold(a, (x, y) => (y > x ? y : x)),
  "math.min": (_c, a) => fold(a, (x, y) => (y < x ? y : x)),
  "math.avg": (_c, a) => {
    let s = 0;
    for (const v of a) s += num(v);
    return s / a.length;
  },

  "str.tostring": (_c, a) => (typeof a[0] === "string" ? a[0] : fmtNum(num(a[0]), num(a[1]))),
  "str.length": (_c, a) => str(a[0]).length,
  "str.contains": (_c, a) => (str(a[0]).includes(str(a[1])) ? 1 : 0),

  "color.new": (_c, a) => colorNew(a[0], num(a[1])),
  "color.rgb": (_c, a) => colorRgb(num(a[0]), num(a[1]), num(a[2]), num(a[3])),

  // ---- arrays
  "array.new": (c, a) => {
    const n = num(a[0]);
    if (n !== Math.floor(n) || n < 0) throw new ScriptRuntimeError("ARRAY SIZE MUST BE A WHOLE NUMBER OF AT LEAST 0");
    addArr(c, n);
    return new ArrVal(new Array(n).fill(a[1]));
  },
  "array.from": (c, a) => {
    addArr(c, a.length);
    return new ArrVal(a.slice());
  },
  "array.push": (c, a) => {
    addArr(c, 1);
    arr(a[0]).a.push(a[1]);
    return NaN;
  },
  "array.pop": (c, a) => {
    const x = arr(a[0]);
    if (x.a.length === 0) return NaN; // empty array: na, not an error (shared rule, docs/review/phase25_B.md)
    addArr(c, -1);
    return x.a.pop();
  },
  "array.shift": (c, a) => {
    const x = arr(a[0]);
    if (x.a.length === 0) return NaN; // empty array: na, not an error (shared rule, docs/review/phase25_B.md)
    addArr(c, -1);
    return x.a.shift();
  },
  "array.unshift": (c, a) => {
    addArr(c, 1);
    arr(a[0]).a.unshift(a[1]);
    return NaN;
  },
  "array.get": (_c, a) => {
    const x = arr(a[0]);
    return x.a[index(a[1], x.a.length)];
  },
  "array.set": (_c, a) => {
    const x = arr(a[0]);
    x.a[index(a[1], x.a.length)] = a[2];
    return NaN;
  },
  "array.size": (_c, a) => arr(a[0]).a.length,
  "array.clear": (c, a) => {
    const x = arr(a[0]);
    addArr(c, -x.a.length);
    x.a.length = 0;
    return NaN;
  },
  "array.sum": (_c, a) => {
    let s = 0;
    for (const v of arr(a[0]).a) s += num(v);
    return s;
  },
  "array.avg": (_c, a) => {
    const x = arr(a[0]).a;
    if (x.length === 0) return NaN;
    let s = 0;
    for (const v of x) s += num(v);
    return s / x.length;
  },
  "array.min": (_c, a) => {
    const x = arr(a[0]).a;
    if (x.length === 0) return NaN;
    let m = num(x[0]);
    for (const v of x) {
      const y = num(v);
      if (y !== y) return NaN;
      if (y < m) m = y;
    }
    return m;
  },
  "array.max": (_c, a) => {
    const x = arr(a[0]).a;
    if (x.length === 0) return NaN;
    let m = num(x[0]);
    for (const v of x) {
      const y = num(v);
      if (y !== y) return NaN;
      if (y > m) m = y;
    }
    return m;
  },
  "array.includes": (_c, a) => (arr(a[0]).a.indexOf(a[1]) >= 0 ? 1 : 0),
  "array.indexof": (_c, a) => arr(a[0]).a.indexOf(a[1]),
  "array.sort": (_c, a) => {
    const x = arr(a[0]).a;
    const desc = a[1] === 1 || a[1] === true;
    // numbers sort by value (na goes last either way); text sorts alphabetically
    x.sort((p, q) => {
      if (typeof p === "number" && typeof q === "number") {
        if (p !== p) return q !== q ? 0 : 1;
        if (q !== q) return -1;
        return desc ? q - p : p - q;
      }
      if (typeof p === "string" && typeof q === "string") return desc ? (q < p ? -1 : q > p ? 1 : 0) : p < q ? -1 : p > q ? 1 : 0;
      throw new ScriptRuntimeError("ARRAY.SORT NEEDS ALL NUMBERS OR ALL TEXT");
    });
    return NaN;
  },
  "array.reverse": (_c, a) => {
    arr(a[0]).a.reverse();
    return NaN;
  },

  // ---- maps
  "map.new": () => new MapVal(),
  "map.put": (c, a) => {
    const m = map(a[0]);
    const k = key(a[1]);
    if (!m.m.has(k)) addMap(c, 1);
    m.m.set(k, a[2]);
    return NaN;
  },
  "map.get": (_c, a) => {
    const v = map(a[0]).m.get(key(a[1]));
    return v === undefined ? NaN : v;
  },
  "map.contains": (_c, a) => (map(a[0]).m.has(key(a[1])) ? 1 : 0),
  "map.remove": (c, a) => {
    if (map(a[0]).m.delete(key(a[1]))) addMap(c, -1);
    return NaN;
  },
  "map.size": (_c, a) => map(a[0]).m.size,
  "map.keys": (c, a) => {
    const ks = [...map(a[0]).m.keys()];
    addArr(c, ks.length);
    return new ArrVal(ks);
  },
  "map.values": (c, a) => {
    const vs = [...map(a[0]).m.values()];
    addArr(c, vs.length);
    return new ArrVal(vs);
  },

  // ---- drawings (x is a bar_index)
  "label.new": (c, a) => keep(c.labels, new LabelH(num(a[0]), num(a[1]), textOf(a[2]), colorOrNull(a[3]), str(a[4]), colorOrNull(a[5])), c.maxLabels),
  "label.delete": (c, a) => {
    drop(c.labels, label(a[0]));
    return NaN;
  },
  "label.set_text": (_c, a) => {
    label(a[0]).text = textOf(a[1]);
    return NaN;
  },
  "label.set_xy": (_c, a) => {
    const l = label(a[0]);
    l.x = num(a[1]);
    l.y = num(a[2]);
    return NaN;
  },
  "line.new": (c, a) => keep(c.lines, new LineH(num(a[0]), num(a[1]), num(a[2]), num(a[3]), colorOrNull(a[4]), num(a[5])), c.maxLabels),
  "line.delete": (c, a) => {
    drop(c.lines, line(a[0]));
    return NaN;
  },
  "line.set_xy2": (_c, a) => {
    const l = line(a[0]);
    l.x2 = num(a[1]);
    l.y2 = num(a[2]);
    return NaN;
  },
  "box.new": (c, a) => keep(c.boxes, new BoxH(num(a[0]), num(a[1]), num(a[2]), num(a[3]), colorOrNull(a[4]), colorOrNull(a[5])), c.maxLabels),
  "box.delete": (c, a) => {
    drop(c.boxes, box(a[0]));
    return NaN;
  },
  "table.new": (c, a) => {
    const cols = num(a[1]);
    const rows = num(a[2]);
    if (!(cols >= 1 && cols <= 100 && cols === Math.floor(cols) && rows >= 1 && rows <= 100 && rows === Math.floor(rows))) {
      throw new ScriptRuntimeError("A TABLE NEEDS 1 TO 100 COLUMNS AND ROWS");
    }
    // One table per screen corner: a new table at a position replaces the old one there, so `t = table.new(...)` run on
    // every bar (no `var`) still shows one table, the last bar's (spec 1.5 "only the state after the last bar is shown").
    const t = new TableH(str(a[0]), cols, rows);
    const at = c.tables.findIndex((x) => x.position === t.position);
    if (at >= 0) c.tables.splice(at, 1);
    c.tables.push(t);
    return t;
  },
  "table.cell": (_c, a) => {
    const t = table(a[0]);
    const col = num(a[1]);
    const row = num(a[2]);
    if (col !== Math.floor(col) || row !== Math.floor(row) || col < 0 || row < 0 || col >= t.columns || row >= t.rows) {
      throw new ScriptRuntimeError("TABLE CELL OUT OF RANGE");
    }
    t.cells.set(row * 1000 + col, { column: col, row, text: textOf(a[3]), color: colorOrNull(a[4]), bgcolor: colorOrNull(a[5]) });
    return NaN;
  },
};

/** The namespace a method call on this value belongs to: `arr.push(x)` is `array.push`, `h.delete()` on a label is `label.delete`. */
export function methodNs(recv: unknown): string {
  return recv instanceof ArrVal ? "array" : recv instanceof MapVal ? "map" : recv instanceof LabelH ? "label" : recv instanceof LineH ? "line" : recv instanceof BoxH ? "box" : recv instanceof TableH ? "table" : "";
}

/** `recv.name(args)`: find the implementation by the receiver's kind (array, map, label, line, box, table). */
export function methodImpl(recv: unknown, name: string): Impl {
  const ns = methodNs(recv);
  const f = ns ? FN[`${ns}.${name}`] : undefined;
  if (!f) throw new ScriptRuntimeError(`${typeName(recv)} HAS NO METHOD ${name.toUpperCase()}`);
  return f;
}
