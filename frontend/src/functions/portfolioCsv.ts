/**
 * Portfolio CSV: a small RFC 4180 reader/writer plus tolerant position import. Pure, unit-tested directly.
 * Import never drops a row silently: each data row ends up in `rows` or in `errors` (with its line number).
 */
import { isSymbolToken } from "../command/markets";

/** Splits CSV text into records. Handles a BOM, CRLF / LF / CR, quoted fields with commas, quotes and newlines. */
export function parseCsv(text: string, delimiter?: string): string[][] {
  const s = text.charCodeAt(0) === 0xfeff ? text.slice(1) : text;
  const d = delimiter ?? sniffDelimiter(s);
  const out: string[][] = [];
  let row: string[] = [];
  let field = "";
  let quoted = false;
  let i = 0;
  const endField = () => {
    row.push(field);
    field = "";
  };
  const endRow = () => {
    endField();
    out.push(row);
    row = [];
  };
  while (i < s.length) {
    const c = s[i];
    if (quoted) {
      if (c === '"') {
        if (s[i + 1] === '"') {
          field += '"';
          i += 2;
          continue;
        }
        quoted = false;
      } else field += c;
      i++;
      continue;
    }
    if (c === '"' && field.trim() === "") {
      field = "";
      quoted = true;
    } else if (c === d) endField();
    else if (c === "\r" || c === "\n") {
      endRow();
      if (c === "\r" && s[i + 1] === "\n") i++;
    } else field += c;
    i++;
  }
  if (field !== "" || row.length) endRow();
  return out;
}

/** Comma unless the first line has more semicolons or tabs (European exports use ';'). */
function sniffDelimiter(s: string): string {
  const first = s.slice(0, s.search(/\r|\n/) === -1 ? s.length : s.search(/\r|\n/)).replace(/"[^"]*"/g, "");
  const count = (ch: string) => first.split(ch).length - 1;
  const best = [",", ";", "\t"].map((ch) => [ch, count(ch)] as const).sort((a, b) => b[1] - a[1])[0];
  return best[1] > 0 ? best[0] : ",";
}

const needsQuotes = (v: string) => /[",\r\n]/.test(v) || v !== v.trim();
const esc = (v: string) => (needsQuotes(v) ? `"${v.replace(/"/g, '""')}"` : v);

/** CRLF line endings (RFC 4180; Excel and every spreadsheet read them). */
export function serializeCsv(rows: string[][]): string {
  return rows.map((r) => r.map(esc).join(",")).join("\r\n") + "\r\n";
}

// --- positions --------------------------------------------------------------------------------
export interface ImportRow {
  line: number;
  symbol: string;
  qty: number;
  cost: number | null;
  currency: string | null;
  notes: string | null;
}

export interface ImportResult {
  rows: ImportRow[];
  errors: { line: number; text: string; reason: string }[];
  warnings: string[];
  /** Field -> the header it was read from (or "COLUMN n" without a header row). */
  mapping: Partial<Record<Field, string>>;
}

type Field = "symbol" | "qty" | "cost" | "total" | "currency" | "notes";

const norm = (h: string) => h.toLowerCase().replace(/[^a-z0-9]/g, "");
const HEADERS: Record<Field, string[]> = {
  symbol: ["symbol", "ticker", "sym", "tickersymbol", "instrument", "security", "code", "stock"],
  qty: ["quantity", "qty", "shares", "units", "position", "holding", "holdings", "amount", "noofshares", "sharesheld"],
  cost: [
    "cost", "avgcost", "averagecost", "avgprice", "averageprice", "price", "costpershare", "unitcost", "purchaseprice",
    "buyprice", "avgbuyprice", "costprice", "averagecostpershare", "avgcostpershare", "pricepaid",
  ],
  total: ["costbasis", "totalcost", "bookvalue", "invested", "totalcostbasis", "investedvalue"],
  currency: ["currency", "ccy", "cur", "curr"],
  notes: ["notes", "note", "comment", "comments", "memo", "description"],
};

function mapHeader(header: string[]): Map<Field, number> {
  const m = new Map<Field, number>();
  header.forEach((h, i) => {
    const n = norm(h);
    for (const f of Object.keys(HEADERS) as Field[]) if (!m.has(f) && HEADERS[f].includes(n)) m.set(f, i);
  });
  return m;
}

/** "1,234.50", "$12", "(10)" (negative), "1 000", "€ 5" -> number; "" -> null; junk -> NaN. */
export function parseAmount(raw: string): number | null {
  let t = raw.trim().replace(/^[$€£₹¥]\s*|\s*[$€£₹¥]$/g, "").replace(/[\s ']/g, "");
  if (!t) return null;
  let neg = false;
  if (/^\(.*\)$/.test(t)) {
    neg = true;
    t = t.slice(1, -1);
  }
  if (/^[+-]?\d{1,3}(,\d{3})+(\.\d+)?$/.test(t)) t = t.replace(/,/g, "");
  if (!/^[+-]?(\d+\.?\d*|\.\d+)(e[+-]?\d+)?$/i.test(t)) return NaN;
  const n = Number(t);
  return neg ? -n : n;
}

const CCY = /^[A-Za-z]{3}$/;

/** Reads positions from CSV text with a tolerant header (symbol/ticker, quantity/qty/shares, cost/avg cost/price). */
export function importPositions(text: string): ImportResult {
  const records = parseCsv(text);
  const res: ImportResult = { rows: [], errors: [], warnings: [], mapping: {} };
  // Line numbers count physical records (a quoted field with a newline counts as one record).
  const numbered = records.map((r, i) => ({ r, line: i + 1 })).filter((x) => x.r.some((c) => c.trim() !== ""));
  if (!numbered.length) {
    res.warnings.push("NO ROWS FOUND");
    return res;
  }
  let cols = mapHeader(numbered[0].r);
  let data = numbered.slice(1);
  if (!cols.has("symbol") || !(cols.has("qty"))) {
    const looksLikeData = numbered[0].r.length >= 2 && Number.isFinite(parseAmount(numbered[0].r[1]) ?? NaN);
    if (cols.size && !looksLikeData) {
      const missing = [!cols.has("symbol") && "SYMBOL", !cols.has("qty") && "QUANTITY"].filter(Boolean).join(" AND ");
      res.errors.push({ line: numbered[0].line, text: numbered[0].r.join(","), reason: `HEADER HAS NO ${missing} COLUMN` });
      for (const x of data) res.errors.push({ line: x.line, text: x.r.join(","), reason: "NOT READ: HEADER NOT RECOGNISED" });
      return res;
    }
    if (!looksLikeData) {
      res.errors.push({ line: numbered[0].line, text: numbered[0].r.join(","), reason: "HEADER NOT RECOGNISED (NEED SYMBOL AND QUANTITY COLUMNS)" });
      for (const x of data) res.errors.push({ line: x.line, text: x.r.join(","), reason: "NOT READ: HEADER NOT RECOGNISED" });
      return res;
    }
    cols = new Map<Field, number>([["symbol", 0], ["qty", 1], ["cost", 2], ["currency", 3], ["notes", 4]]);
    data = numbered;
    res.warnings.push("NO HEADER ROW: COLUMNS READ AS SYMBOL, QUANTITY, COST, CURRENCY, NOTES");
    for (const [f, i] of cols) res.mapping[f] = `COLUMN ${i + 1}`;
  } else {
    for (const [f, i] of cols) res.mapping[f] = numbered[0].r[i].trim();
    if (cols.has("total") && !cols.has("cost")) res.warnings.push(`AVG COST = ${res.mapping.total} / QUANTITY`);
  }

  const cell = (r: string[], f: Field) => (cols.has(f) ? (r[cols.get(f)!] ?? "").trim() : "");
  const seen = new Map<string, number[]>();
  for (const { r, line } of data) {
    const text = r.join(",");
    const fail = (reason: string) => res.errors.push({ line, text, reason });
    const symbol = cell(r, "symbol").toUpperCase();
    if (!symbol) {
      fail("NO SYMBOL");
      continue;
    }
    if (!isSymbolToken(symbol) || symbol.length > 24) {
      fail(`BAD SYMBOL: ${symbol.slice(0, 24)}`);
      continue;
    }
    const qty = parseAmount(cell(r, "qty"));
    if (qty === null || Number.isNaN(qty)) {
      fail(qty === null ? "NO QUANTITY" : `BAD QUANTITY: ${cell(r, "qty")}`);
      continue;
    }
    if (qty === 0) {
      fail("QUANTITY IS 0");
      continue;
    }
    let cost: number | null = null;
    if (cols.has("cost")) {
      cost = parseAmount(cell(r, "cost"));
    } else if (cols.has("total")) {
      const total = parseAmount(cell(r, "total"));
      cost = total === null || Number.isNaN(total) ? total : Math.abs(total / qty);
    }
    if (cost !== null && (Number.isNaN(cost) || cost < 0)) {
      fail(`BAD COST: ${cell(r, cols.has("cost") ? "cost" : "total")}`);
      continue;
    }
    const ccyRaw = cell(r, "currency");
    if (ccyRaw && !CCY.test(ccyRaw)) {
      fail(`BAD CURRENCY: ${ccyRaw}`);
      continue;
    }
    const currency = ccyRaw ? (ccyRaw === "GBp" || ccyRaw === "ZAc" ? ccyRaw : ccyRaw.toUpperCase()) : null;
    const notes = cell(r, "notes").slice(0, 200) || null;
    res.rows.push({ line, symbol, qty, cost, currency, notes });
    seen.set(symbol, [...(seen.get(symbol) ?? []), line]);
  }
  for (const [sym, lines] of seen) {
    if (lines.length > 1) res.warnings.push(`${sym} ON LINES ${lines.join(", ")}: COMBINED AS LOTS (AVERAGE COST)`);
  }
  return res;
}

export interface ExportPosition {
  symbol: string;
  qty: number;
  cost: number | null;
  currency: string | null;
  notes: string | null;
}

export const EXPORT_HEADER = ["symbol", "quantity", "avg_cost", "currency", "notes", "last", "market_value", "unrealized_pnl"];

const num = (n: number | null | undefined) => (n == null || !Number.isFinite(n) ? "" : String(Math.round(n * 1e8) / 1e8));

/** Re-importable CSV: the position columns first, then live values at export time (ignored on import). */
export function exportPositions(positions: ExportPosition[], last: (symbol: string) => number | null = () => null): string {
  const rows = positions.map((p) => {
    const px = last(p.symbol);
    const mv = px == null ? null : px * p.qty;
    const unrl = px == null || p.cost == null ? null : (px - p.cost) * p.qty;
    return [p.symbol, num(p.qty), num(p.cost), p.currency ?? "", p.notes ?? "", num(px), num(mv), num(unrl)];
  });
  return serializeCsv([EXPORT_HEADER, ...rows]);
}
