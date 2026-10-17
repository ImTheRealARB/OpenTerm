/**
 * EQS filter grammar (pure, unit-tested). Example:
 *   EQS SECTOR=TECH MCAP>10B PCT>2 PRICE<50 VOL>1M COUNTRY=US SORT=PCT
 *
 * Terms are ANDed. Numeric fields take > >= < <= = != with K/M/B/T suffixes (and an optional % or $).
 * Text fields (SECTOR, INDUSTRY, COUNTRY) take = or != with comma-separated values; each value is a
 * case-insensitive prefix of the name or of one of its words ("TECH" = Technology, "STAPLES" = Consumer Staples;
 * use _ for spaces: CONSUMER_D). NAME= is a substring match. A bare word is tried as a sector, then an industry.
 * SORT=KEY sorts descending for numbers and ascending for text; SORT=+KEY / SORT=-KEY forces the direction.
 */

/** One screener row, as served by /api/screener (columnar, with lookup-table indexes). */
export type UniverseRow = [
  symbol: string,
  name: string,
  last: number | null,
  chg: number | null,
  pct: number | null,
  volume: number | null,
  mcap: number | null,
  country: number,
  ipo: number | null,
  sector: number,
  industry: number,
];

export interface Universe {
  rows: UniverseRow[];
  sectors: string[];
  industries: string[];
  countries: string[];
}

const NUMERIC = { PRICE: 2, CHG: 3, PCT: 4, VOL: 5, MCAP: 6, IPO: 8 } as const;
const TEXT = { SECTOR: 9, INDUSTRY: 10, COUNTRY: 7 } as const;
type NumField = keyof typeof NUMERIC;
type TextField = keyof typeof TEXT;
export type SortKey = NumField | "SYMBOL" | "NAME";

const ALIASES: Record<string, string> = {
  LAST: "PRICE", PX: "PRICE", "%CHG": "PCT", "CHG%": "PCT", PCTCHG: "PCT", VOLUME: "VOL", CAP: "MCAP",
  MKTCAP: "MCAP", MARKETCAP: "MCAP", IND: "INDUSTRY", SEC: "SECTOR", CTRY: "COUNTRY", SYM: "SYMBOL", TICKER: "SYMBOL",
};

const COUNTRY_CODES: Record<string, string> = {
  US: "United States", USA: "United States", UK: "United Kingdom", GB: "United Kingdom", CN: "China", CA: "Canada",
  IL: "Israel", HK: "Hong Kong", SG: "Singapore", IN: "India", JP: "Japan", DE: "Germany", CH: "Switzerland",
  NL: "Netherlands", IE: "Ireland", BR: "Brazil", MX: "Mexico", AU: "Australia", FR: "France", KR: "South Korea",
  TW: "Taiwan", AR: "Argentina", BM: "Bermuda", KY: "Cayman Islands", LU: "Luxembourg", GR: "Greece", SE: "Sweden",
};

const SUFFIX: Record<string, number> = { K: 1e3, M: 1e6, B: 1e9, T: 1e12 };

export type Op = ">" | ">=" | "<" | "<=" | "=" | "!=";

export type Clause =
  | { kind: "num"; field: NumField; op: Op; value: number; text: string }
  | { kind: "text"; field: TextField; neg: boolean; values: string[]; text: string }
  | { kind: "name"; neg: boolean; value: string; text: string }
  | { kind: "bare"; value: string; text: string };

export interface ParsedFilter {
  clauses: Clause[];
  sort: { key: SortKey; dir: 1 | -1 } | null;
  errors: string[];
}

/** "10B" -> 1e10, "1.5M" -> 1.5e6, "2%" -> 2, "$50" -> 50, "-3" -> -3. Null if not a number. */
export function parseNumber(s: string): number | null {
  const m = /^\$?(-?\d+(?:\.\d+)?|-?\.\d+)([KMBT])?%?$/i.exec(s.trim());
  if (!m) return null;
  return Number(m[1]) * (m[2] ? SUFFIX[m[2].toUpperCase()] : 1);
}

const TERM = /^([A-Z%][A-Z%_]*)(>=|<=|!=|=|>|<)(.+)$/i;

export function parseFilter(args: string[]): ParsedFilter {
  // Allow spaces around operators: "MCAP > 10B" -> "MCAP>10B".
  const joined = args.join(" ").replace(/\s*(>=|<=|!=|=|>|<)\s*/g, "$1").trim();
  const tokens = joined ? joined.split(/\s+/) : [];
  const out: ParsedFilter = { clauses: [], sort: null, errors: [] };
  for (const tok of tokens) {
    const m = TERM.exec(tok);
    if (!m) {
      if (/^[A-Z][A-Z_&-]*$/i.test(tok)) out.clauses.push({ kind: "bare", value: norm(tok), text: tok.toUpperCase() });
      else out.errors.push(`CANNOT READ ${tok.toUpperCase()}`);
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
      if (!(key in NUMERIC) && key !== "SYMBOL" && key !== "NAME") {
        out.errors.push(`CANNOT SORT BY ${keyRaw}`);
        continue;
      }
      const natural: 1 | -1 = key === "SYMBOL" || key === "NAME" ? 1 : -1;
      out.sort = { key, dir: dirCh === "+" ? 1 : dirCh === "-" ? -1 : natural };
      continue;
    }
    if (field in NUMERIC) {
      const n = parseNumber(val);
      if (n === null) out.errors.push(`${field}: ${val.toUpperCase()} IS NOT A NUMBER`);
      else out.clauses.push({ kind: "num", field: field as NumField, op, value: n, text });
      continue;
    }
    if (field in TEXT || field === "NAME") {
      if (op !== "=" && op !== "!=") {
        out.errors.push(`${field} TAKES = OR !=`);
        continue;
      }
      if (field === "NAME") out.clauses.push({ kind: "name", neg: op === "!=", value: norm(val), text });
      else {
        const values = val.split(",").map(norm).filter(Boolean);
        if (!values.length) out.errors.push(`${field}: NO VALUE`);
        else out.clauses.push({ kind: "text", field: field as TextField, neg: op === "!=", values, text });
      }
      continue;
    }
    out.errors.push(`UNKNOWN FIELD ${rawField}`);
  }
  return out;
}

const norm = (s: string) => s.replace(/_/g, " ").replace(/\s+/g, " ").trim().toLowerCase();

/** Case-insensitive prefix of the whole name or of any of its words. */
export function prefixMatch(name: string, value: string): boolean {
  const n = name.toLowerCase();
  if (!n || !value) return false;
  if (n.startsWith(value)) return true;
  return n.split(/[\s:,&/()-]+/).some((w) => w && w.startsWith(value));
}

/** Indexes into a lookup table (sector / industry / country names) matched by any of the values. */
export function matchTable(table: string[], values: string[], countryCodes = false): Set<number> {
  const hit = new Set<number>();
  for (const v of values) {
    const code = countryCodes ? COUNTRY_CODES[v.toUpperCase()] : undefined;
    table.forEach((name, i) => {
      if (code ? name === code : prefixMatch(name, v)) hit.add(i);
    });
  }
  return hit;
}

export interface CompiledFilter {
  test: (r: UniverseRow) => boolean;
  /** Human-readable terms after resolution, e.g. "SECTOR=TECHNOLOGY". */
  terms: string[];
  errors: string[];
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

export function compileFilter(f: ParsedFilter, u: Universe): CompiledFilter {
  const errors = [...f.errors];
  const terms: string[] = [];
  const tests: ((r: UniverseRow) => boolean)[] = [];
  const tables: Record<TextField, string[]> = { SECTOR: u.sectors, INDUSTRY: u.industries, COUNTRY: u.countries };
  const label = (table: string[], hit: Set<number>) => {
    const names = [...hit].map((i) => table[i].toUpperCase());
    return names.length > 3 ? `${names.slice(0, 3).join(",")} +${names.length - 3}` : names.join(",");
  };
  for (const c of f.clauses) {
    if (c.kind === "num") {
      const col = NUMERIC[c.field];
      tests.push((r) => cmp(r[col] as number | null, c.op, c.value));
      terms.push(c.text);
    } else if (c.kind === "name") {
      tests.push((r) => r[1].toLowerCase().includes(c.value) !== c.neg);
      terms.push(c.text);
    } else {
      let field: TextField | null = null;
      let hit = new Set<number>();
      if (c.kind === "text") {
        field = c.field;
        hit = matchTable(tables[field], c.values, field === "COUNTRY");
      } else {
        for (const fld of ["SECTOR", "INDUSTRY"] as const) {
          hit = matchTable(tables[fld], [c.value]);
          if (hit.size) {
            field = fld;
            break;
          }
        }
      }
      if (!field || !hit.size) {
        errors.push(c.kind === "bare" ? `NO SECTOR OR INDUSTRY MATCHES ${c.text}` : `NO ${c.field} MATCHES ${c.values.join(",").toUpperCase()}`);
        tests.push(() => false);
        continue;
      }
      const col = TEXT[field];
      const neg = c.kind === "text" && c.neg;
      tests.push((r) => hit.has(r[col] as number) !== neg);
      terms.push(`${field}${neg ? "!=" : "="}${label(tables[field], hit)}`);
    }
  }
  return { test: (r) => tests.every((t) => t(r)), terms, errors };
}

const SORT_COL: Record<SortKey, number> = { ...NUMERIC, SYMBOL: 0, NAME: 1 };

/** Matching rows, sorted (default: market cap, largest first). Nulls always sort last. */
export function screen(u: Universe, f: ParsedFilter): { rows: UniverseRow[]; compiled: CompiledFilter } {
  const compiled = compileFilter(f, u);
  const rows = u.rows.filter(compiled.test);
  const sort = f.sort ?? { key: "MCAP" as SortKey, dir: -1 as const };
  const col = SORT_COL[sort.key];
  rows.sort((a, b) => {
    const x = a[col];
    const y = b[col];
    if (x === y) return 0;
    if (x === null) return 1;
    if (y === null) return -1;
    return (typeof x === "string" ? x.localeCompare(y as string) : (x as number) - (y as number)) * sort.dir;
  });
  return { rows, compiled };
}
