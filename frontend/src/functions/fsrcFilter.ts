/**
 * FSRC filter grammar (pure, unit-tested). Example:
 *   FSRC FEE<0.2 AUM>1B CAT=LARGE SORT=AUM
 *
 * It is a small cousin of the EQS grammar (eqsFilter.ts, whose number parser and word matcher it reuses). Terms are ANDed.
 *   FEE   yearly fee (expense ratio) in PERCENT: FEE<0.2 means "under 0.2% a year". Takes > >= < <= = !=
 *   AUM   total assets (the fund's size) in dollars with K / M / B / T suffixes: AUM>1B. Same operators.
 *   CAT   category, = or != with comma-separated values; each value is a case-insensitive prefix of the category name or of one
 *         of its words ("LARGE" = Large Blend, Large Growth, Large Value; use _ for a space: CAT=LARGE_BLEND).
 *   SORT  FEE | AUM | SYMBOL | NAME | CAT. Fee and text sort ascending (cheapest first), size sorts largest first;
 *         SORT=+KEY / SORT=-KEY forces the direction. Default: AUM, largest first.
 * A fund with no value for a field never passes a number test on that field (an unknown fee is not "under 0.2%").
 */
import type { FsrcRow } from "../net/etfTypes";
import { parseNumber, prefixMatch, type Op } from "./eqsFilter";

const NUMERIC = { FEE: 2, AUM: 3 } as const;
type NumField = keyof typeof NUMERIC;
export type SortKey = NumField | "SYMBOL" | "NAME" | "CAT";
const SORT_COL: Record<SortKey, number> = { FEE: 2, AUM: 3, SYMBOL: 0, NAME: 1, CAT: 4 };
/** Ascending is the natural order for text and for fees (cheapest first); descending for size. */
const NATURAL: Record<SortKey, 1 | -1> = { FEE: 1, AUM: -1, SYMBOL: 1, NAME: 1, CAT: 1 };

const ALIASES: Record<string, string> = {
  EXPENSE: "FEE", EXP: "FEE", ER: "FEE", ASSETS: "AUM", SIZE: "AUM", TNA: "AUM", CATEGORY: "CAT", SYM: "SYMBOL", TICKER: "SYMBOL",
};

export type Clause =
  | { kind: "num"; field: NumField; op: Op; value: number; text: string }
  | { kind: "cat"; neg: boolean; values: string[]; text: string };

export interface FsrcFilter {
  clauses: Clause[];
  sort: { key: SortKey; dir: 1 | -1 } | null;
  errors: string[];
}

const TERM = /^([A-Z%][A-Z%_]*)(>=|<=|!=|=|>|<)(.+)$/i;
const norm = (s: string) => s.replace(/_/g, " ").replace(/\s+/g, " ").trim().toLowerCase();

export function parseFsrcFilter(args: string[]): FsrcFilter {
  // Spaces around an operator are allowed: "FEE < 0.2" -> "FEE<0.2".
  const joined = args.join(" ").replace(/\s*(>=|<=|!=|=|>|<)\s*/g, "$1").trim();
  const out: FsrcFilter = { clauses: [], sort: null, errors: [] };
  for (const tok of joined ? joined.split(/\s+/) : []) {
    const m = TERM.exec(tok);
    if (!m) {
      out.errors.push(`CANNOT READ ${tok.toUpperCase()}`);
      continue;
    }
    const rawField = m[1].toUpperCase();
    const field = ALIASES[rawField] ?? rawField;
    const op = m[2] as Op;
    const val = m[3];
    const text = `${field}${op}${val.toUpperCase()}`;
    if (field === "SORT") {
      if (op !== "=") {
        out.errors.push("SORT TAKES =");
        continue;
      }
      const dirCh = val[0] === "+" || val[0] === "-" ? val[0] : "";
      const keyRaw = val.slice(dirCh.length).toUpperCase();
      const key = (ALIASES[keyRaw] ?? keyRaw) as SortKey;
      if (!(key in SORT_COL)) {
        out.errors.push(`CANNOT SORT BY ${keyRaw}`);
        continue;
      }
      out.sort = { key, dir: dirCh === "+" ? 1 : dirCh === "-" ? -1 : NATURAL[key] };
    } else if (field in NUMERIC) {
      const n = parseNumber(val);
      if (n === null) out.errors.push(`${field}: ${val.toUpperCase()} IS NOT A NUMBER`);
      else out.clauses.push({ kind: "num", field: field as NumField, op, value: n, text });
    } else if (field === "CAT") {
      if (op !== "=" && op !== "!=") {
        out.errors.push("CAT TAKES = OR !=");
        continue;
      }
      const values = val.split(",").map(norm).filter(Boolean);
      if (!values.length) out.errors.push("CAT: NO VALUE");
      else out.clauses.push({ kind: "cat", neg: op === "!=", values, text });
    } else out.errors.push(`UNKNOWN FIELD ${rawField}`);
  }
  return out;
}

const cmp = (v: number | null, op: Op, x: number) => {
  if (v === null) return false; // unknown values never pass a numeric filter
  switch (op) {
    case ">": return v > x;
    case ">=": return v >= x;
    case "<": return v < x;
    case "<=": return v <= x;
    case "=": return v === x;
    case "!=": return v !== x;
  }
};

export interface Screened {
  rows: FsrcRow[];
  /** The terms as understood, e.g. "FEE<0.2". */
  terms: string[];
  errors: string[];
}

/**
 * The rows that pass, sorted. `complete` says whether the table has finished loading: a category that matches nothing is an error
 * only then (while rows are still arriving, its category may simply not have been loaded yet).
 */
export function screenFsrc(all: FsrcRow[], f: FsrcFilter, complete: boolean): Screened {
  const errors = [...f.errors];
  const tests: ((r: FsrcRow) => boolean)[] = [];
  let cats: string[] | null = null; // the distinct category names, built only when a CAT term needs them
  for (const c of f.clauses) {
    if (c.kind === "num") {
      const col = NUMERIC[c.field];
      tests.push((r) => cmp(r[col], c.op, c.value));
    } else {
      const names = (cats ??= [...new Set(all.map((r) => r[4]).filter((x): x is string => !!x))]);
      if (complete && !c.values.some((v) => names.some((name) => prefixMatch(name, v)))) errors.push(`NO CATEGORY MATCHES ${c.values.join(",").toUpperCase()}`);
      tests.push((r) => c.values.some((v) => r[4] != null && prefixMatch(r[4], v)) !== c.neg);
    }
  }
  const rows = all.filter((r) => tests.every((t) => t(r)));
  const sort = f.sort ?? { key: "AUM" as SortKey, dir: -1 as const };
  const col = SORT_COL[sort.key];
  rows.sort((a, b) => {
    const x = a[col];
    const y = b[col];
    if (x === y) return 0;
    if (x === null) return 1; // unknowns last, whichever way it sorts
    if (y === null) return -1;
    return (typeof x === "string" ? x.localeCompare(y as string) : (x as number) - (y as number)) * sort.dir;
  });
  return { rows, terms: f.clauses.map((c) => c.text), errors };
}
