/**
 * OpenTerm Script runtime values and small helpers shared by the compiler, built-ins and runtime.
 *
 * How values are stored while a script runs (no class per value, to keep the per-bar loop fast):
 *   number   a JS number. `na` (missing) is NaN. A true/false result is 1 or 0 (so `plot(a > b)` draws 0/1).
 *   string   a JS string.
 *   color    a JS string "#rrggbb" or "#rrggbbaa". `na` colour = NaN ("no colour").
 *   array    ArrVal      map  MapVal      drawings  LabelH / LineH / BoxH / TableH      plot handle  PlotH
 */
import type { Pos } from "./ast";

export class ArrVal {
  constructor(public a: unknown[] = []) {}
}
export class MapVal {
  constructor(public m: Map<string | number, unknown> = new Map()) {}
}
/** What `plot(...)` returns: the index of the plot in the result (only `fill` uses it). */
export class PlotH {
  constructor(public idx: number) {}
}
export class LabelH {
  dead = false;
  constructor(
    public x: number,
    public y: number,
    public text: string,
    public color: string | null,
    public style: string,
    public textcolor: string | null,
  ) {}
}
export class LineH {
  dead = false;
  constructor(
    public x1: number,
    public y1: number,
    public x2: number,
    public y2: number,
    public color: string | null,
    public width: number,
  ) {}
}
export class BoxH {
  dead = false;
  constructor(
    public left: number,
    public top: number,
    public right: number,
    public bottom: number,
    public color: string | null,
    public bgcolor: string | null,
  ) {}
}
export interface TableCell {
  column: number;
  row: number;
  text: string;
  color: string | null;
  bgcolor: string | null;
}
export class TableH {
  dead = false;
  /** keyed by `row * 1000 + column` */
  cells = new Map<number, TableCell>();
  constructor(
    public position: string,
    public columns: number,
    public rows: number,
  ) {}
}

/** A run-time error. `pos` is filled in by the call that failed (see compile.ts) so the host can show the line. */
export class ScriptRuntimeError extends Error {
  constructor(
    msg: string,
    public pos?: Pos,
  ) {
    super(msg);
  }
}

/** "true" in `if` / `and` / `or` / `?:`: a number that is not na and not 0. Other values (text, lists) count as true. */
export function truth(v: unknown): boolean {
  if (typeof v === "number") return v !== 0 && v === v;
  return v !== undefined && v !== null && v !== "";
}

/** The readable name of a value's type, for error messages. */
export function typeName(v: unknown): string {
  if (typeof v === "number") return "NUMBER";
  if (typeof v === "string") return v.startsWith("#") ? "COLOUR OR TEXT" : "TEXT";
  if (v instanceof ArrVal) return "ARRAY";
  if (v instanceof MapVal) return "MAP";
  if (v instanceof LabelH) return "LABEL";
  if (v instanceof LineH) return "LINE";
  if (v instanceof BoxH) return "BOX";
  if (v instanceof TableH) return "TABLE";
  if (v instanceof PlotH) return "PLOT";
  return "NOTHING";
}

/** Number to text for `str.tostring`. decimals < 0: shortest text that reads back exactly, whole numbers with no ".0". */
export function fmtNum(x: number, decimals: number): string {
  if (x !== x) return "na";
  if (decimals < 0) return String(x);
  return x.toFixed(Math.min(100, Math.floor(decimals)));
}

const hex2 = (n: number) => (n < 16 ? "0" : "") + n.toString(16);
const clamp255 = (n: number) => Math.min(255, Math.max(0, Math.round(n)));

/** `color.new(c, transp)`: the same colour with transparency 0 (solid) to 100 (invisible). Result is "#rrggbb" when solid. */
export function colorNew(c: unknown, transp: number): string | number {
  if (typeof c !== "string" || !/^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$/.test(c)) return NaN;
  if (transp !== transp) return NaN;
  const t = Math.min(100, Math.max(0, transp));
  const alpha = clamp255((255 * (100 - t)) / 100);
  const base = c.slice(0, 7).toLowerCase();
  return alpha === 255 ? base : base + hex2(alpha);
}

/** `color.rgb(r, g, b, transp)`. */
export function colorRgb(r: number, g: number, b: number, transp: number): string | number {
  if (r !== r || g !== g || b !== b) return NaN;
  const base = "#" + hex2(clamp255(r)) + hex2(clamp255(g)) + hex2(clamp255(b));
  if (transp !== transp) return NaN;
  const alpha = clamp255((255 * (100 - Math.min(100, Math.max(0, transp)))) / 100);
  return alpha === 255 ? base : base + hex2(alpha);
}

/** A colour value to what the result stores: a string, or null for `na` / not a colour. */
export function colorOrNull(v: unknown): string | null {
  return typeof v === "string" && v.startsWith("#") ? v : null;
}

/**
 * Copy a value graph (variables, arrays, maps, drawings) keeping shared references shared: if two variables hold the
 * same array, the copy has ONE new array held by both. Used to snapshot / restore the state at the start of the last
 * bar for live ticks (runtime.ts).
 */
export function cloneValue(v: unknown, seen: Map<object, object>): unknown {
  if (typeof v !== "object" || v === null) return v;
  const done = seen.get(v);
  if (done) return done;
  if (v instanceof ArrVal) {
    const c = new ArrVal([]);
    seen.set(v, c);
    const src = v.a;
    const out = new Array<unknown>(src.length);
    for (let i = 0; i < src.length; i++) out[i] = cloneValue(src[i], seen);
    c.a = out;
    return c;
  }
  if (v instanceof MapVal) {
    const c = new MapVal();
    seen.set(v, c);
    for (const [k, x] of v.m) c.m.set(k, cloneValue(x, seen));
    return c;
  }
  if (v instanceof TableH) {
    const c = new TableH(v.position, v.columns, v.rows);
    seen.set(v, c);
    c.dead = v.dead;
    for (const [k, cell] of v.cells) c.cells.set(k, { ...cell });
    return c;
  }
  if (v instanceof LabelH || v instanceof LineH || v instanceof BoxH || v instanceof PlotH) {
    const c = Object.assign(Object.create(Object.getPrototypeOf(v)), v) as object;
    seen.set(v, c);
    return c;
  }
  return v;
}
