/**
 * Phase 6 payload types and pure table shaping for FA, FIL, OWN and HDS.
 * No imports from net/core or perf/metrics, so vitest can run it in Node.
 */

export type StatementTab = "IS" | "BS" | "CF";
export type FaPeriod = "A" | "Q";
export const STATEMENT_TABS: [StatementTab, string][] = [
  ["IS", "INCOME STATEMENT"],
  ["BS", "BALANCE SHEET"],
  ["CF", "CASH FLOW"],
];

export interface FaPeriodInfo {
  key: string;
  label: string;
  end: string;
  start: string | null;
  fy: number | null;
  fp: string | null;
  form: string | null;
  filed: string | null;
  /** Some cell in this column is derived (YTD minus a shorter YTD, e.g. Q4 = FY - 9M). */
  derived: boolean;
}

export interface FaRowData {
  key: string;
  label: string;
  unit: "USD" | "USD/shares" | "shares" | string;
  values: (number | null)[];
  /** Per period: "" reported, "d" derived by subtraction, "c" computed by formula. */
  flags: string[];
  /** Per period: the us-gaap tag (or formula) the value came from. */
  tags: (string | null)[];
  computed?: boolean;
}

export interface FaPayload {
  symbol: string;
  cik: number;
  name: string | null;
  currency: string;
  period: FaPeriod;
  periods: FaPeriodInfo[];
  statements: Record<StatementTab, FaRowData[]>;
  source: string;
}

export interface Filing {
  accession: string;
  filed: string;
  report_date: string | null;
  form: string;
  description: string;
  items: string | null;
  primary_doc: string | null;
  url: string;
  doc_url: string | null;
}

export interface FilingsPayload {
  symbol: string;
  cik: number;
  name: string | null;
  fiscal_year_end: string | null;
  sic: string | null;
  form: string | null;
  total: number;
  filings: Filing[];
  source: string;
}

export interface InsiderTrade {
  owner: string;
  owner_cik: string | null;
  relation: string;
  date: string | null;
  code: string;
  code_text: string;
  acq_disp: "A" | "D" | null;
  shares: number | null;
  price: number | null;
  value: number | null;
  owned_after: number | null;
  direct: string | null;
  security: string | null;
  derivative: boolean;
  accession: string | null;
  filed: string | null;
  url: string | null;
}

export interface InsidersPayload {
  symbol: string;
  cik: number | null;
  name: string | null;
  trades: InsiderTrade[];
  filings_read: number | null;
  failed: string[];
  source: string;
}

export interface Holder {
  holder: string;
  pct_held: number | null;
  shares: number | null;
  value: number | null;
  pct_change: number | null;
  report_date: string | null;
}

export interface HoldersPayload {
  symbol: string;
  breakdown: {
    insiders_pct: number | null;
    institutions_pct: number | null;
    institutions_float_pct: number | null;
    institutions_count: number | null;
  };
  institutions: Holder[];
  funds: Holder[];
  source: string;
}

const DASH = "—";

/** FA args in any order: A|Q (annual/quarterly) and IS|BS|CF. */
export function faArgs(args: string[]): { period: FaPeriod; tab: StatementTab } {
  let period: FaPeriod = "A";
  let tab: StatementTab = "IS";
  for (const raw of args) {
    const a = raw.toUpperCase();
    if (a === "A" || a === "Q") period = a;
    else if (a === "IS" || a === "BS" || a === "CF") tab = a;
  }
  return { period, tab };
}

/** Statement cells: USD and share counts in millions, per-share values with 2 decimals. */
export function fmtStatement(v: number | null | undefined, unit: string): string {
  if (v == null || !Number.isFinite(v)) return DASH;
  if (unit === "USD/shares") return v.toFixed(2);
  const m = v / 1e6;
  const d = Math.abs(m) < 10 ? 1 : 0;
  return m.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
}

export interface FaGridRow {
  key: string;
  label: string;
  unit: string;
  cells: string[];
  flags: string[];
  tags: (string | null)[];
  computed: boolean;
}

/** One grid row per statement line; `offset` hides the newest periods (H/L scroll), `max` caps the columns. */
export function faRows(p: FaPayload, tab: StatementTab, offset = 0, max = 12): { periods: FaPeriodInfo[]; rows: FaGridRow[] } {
  const start = Math.max(0, Math.min(offset, Math.max(0, p.periods.length - 1)));
  const end = Math.min(p.periods.length, start + max);
  const rows = (p.statements[tab] ?? []).map((r) => {
    const cells: string[] = [];
    const flags: string[] = [];
    for (let i = start; i < end; i++) {
      const f = r.flags[i] ?? "";
      // Derived quarters carry a trailing "*"; the footer explains it.
      cells.push(fmtStatement(r.values[i], r.unit) + (f === "d" && r.values[i] != null ? "*" : ""));
      flags.push(f);
    }
    return { key: r.key, label: r.label, unit: r.unit, cells, flags, tags: r.tags.slice(start, end), computed: !!r.computed };
  });
  return { periods: p.periods.slice(start, end), rows };
}

export const unitNote = (unit: string) => (unit === "USD/shares" ? "USD PER SHARE" : unit === "shares" ? "MILLIONS OF SHARES" : "USD MILLIONS");

/** FIL form filter: `FIL 10-K` matches 10-K and 10-K/A. Empty = all. */
export function filingForm(args: string[]): string {
  return (args[0] ?? "").trim().toUpperCase();
}

export function fmtShares(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return DASH;
  return Math.round(v).toLocaleString("en-US");
}

/** Fractions (0.0797) as percent text. */
export function fmtFrac(v: number | null | undefined, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return DASH;
  return (v * 100).toFixed(digits) + "%";
}

export interface HolderRow {
  /** Set on section header rows. */
  section?: string;
  holder: string;
  pct: string;
  shares: number | null;
  value: number | null;
  pct_change: number | null;
  date: string;
}

/** HDS: summary breakdown, then top institutions, then top funds, each under a header row. */
export function holderRows(p: HoldersPayload): HolderRow[] {
  const b = p.breakdown;
  const head = (section: string): HolderRow => ({ section, holder: "", pct: "", shares: null, value: null, pct_change: null, date: "" });
  const kv = (holder: string, pct: string): HolderRow => ({ holder, pct, shares: null, value: null, pct_change: null, date: "" });
  const list = (hs: Holder[]) =>
    hs.map((h) => ({ holder: h.holder, pct: fmtFrac(h.pct_held), shares: h.shares, value: h.value, pct_change: h.pct_change, date: h.report_date ?? "" }));
  const out: HolderRow[] = [
    head("MAJOR HOLDERS"),
    kv("Insiders", fmtFrac(b.insiders_pct)),
    kv("Institutions", fmtFrac(b.institutions_pct)),
    kv("Institutions (of float)", fmtFrac(b.institutions_float_pct)),
    kv("Number of institutions", b.institutions_count == null ? DASH : String(b.institutions_count)),
  ];
  if (p.institutions.length) out.push(head("TOP INSTITUTIONS"), ...list(p.institutions));
  if (p.funds.length) out.push(head("TOP FUNDS"), ...list(p.funds));
  return out;
}

/** OWN totals over the listed open-market trades (codes P and S). */
export function insiderTotals(trades: InsiderTrade[]): { bought: number; sold: number } {
  let bought = 0;
  let sold = 0;
  for (const t of trades) {
    if (t.code === "P" && t.value) bought += t.value;
    if (t.code === "S" && t.value) sold += t.value;
  }
  return { bought, sold };
}
