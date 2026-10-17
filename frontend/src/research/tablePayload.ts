/**
 * Phase 13: the table payload every research function answers (backend research/table.py), and how a cell prints.
 * Pure (no window), so it is unit-tested. Cells never invent a value: null prints as a dash.
 */
import type { CellColor, Column } from "../components/Grid";

export type Kind = "text" | "int" | "num" | "pct" | "money" | "price" | "date";

export interface TableColumn {
  key: string;
  title: string;
  kind: Kind;
  align: "left" | "right";
  width?: number;
}

export type TableRow = Record<string, string | number | boolean | null> & { url?: string | null };

export interface TableSection {
  id: string;
  title: string;
  columns: TableColumn[];
  rows: TableRow[];
  note: string | null;
}

export interface Headline {
  label: string;
  value: string;
  raw?: number | string;
}

export interface TablePayload {
  symbol: string | null;
  title: string;
  headline: Headline[];
  sections: TableSection[];
  notes: string[];
  key_required: { key: string; what: string }[];
  source: string | null;
}

const DASH = "—";

function grouped(v: number, digits: number): string {
  return v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function big(v: number): string {
  const a = Math.abs(v);
  if (a >= 1e12) return (v / 1e12).toFixed(2) + "T";
  if (a >= 1e9) return (v / 1e9).toFixed(2) + "B";
  if (a >= 1e6) return (v / 1e6).toFixed(2) + "M";
  if (a >= 1e3) return (v / 1e3).toFixed(1) + "K";
  return v.toFixed(0);
}

/** One cell as text. `pct` cells hold ratios (0.0452 prints +4.52%). */
export function cellText(kind: Kind, v: unknown): string {
  if (v == null || v === "") return DASH;
  if (kind === "text" || kind === "date") return String(v);
  if (typeof v !== "number" || !Number.isFinite(v)) return DASH;
  switch (kind) {
    case "int":
      return grouped(v, 0);
    case "num":
      return grouped(v, 2);
    case "price":
      return grouped(v, Math.abs(v) >= 1 ? 2 : 4);
    case "money":
      return big(v);
    case "pct":
      return (v > 0 ? "+" : "") + (v * 100).toFixed(2) + "%";
  }
}

const SIGNED_KEY = /growth|change|surprise|upside|diff|chg/i;

/** Colour carries meaning: only change-like percentage and number columns are signed. */
export function cellColor(col: TableColumn, v: unknown): CellColor {
  if (typeof v === "number" && (col.kind === "pct" || col.kind === "num") && SIGNED_KEY.test(col.key)) return v > 0 ? "up" : v < 0 ? "down" : "fg";
  if (col.kind === "date") return "dim";
  return "fg";
}

const MIN_W = 4;
const MAX_W = 44;

/** Grid columns for a section; width = widest of the title, a backend hint and the first 200 cells. */
export function gridColumns(s: TableSection): Column<TableRow>[] {
  return s.columns.map((c, i) => {
    let w = Math.max(c.title.length, c.width ?? 0, MIN_W);
    for (const r of s.rows.slice(0, 200)) w = Math.max(w, cellText(c.kind, r[c.key]).length);
    return {
      title: c.title,
      width: Math.min(w, MAX_W),
      align: c.align,
      text: (r: TableRow) => cellText(c.kind, r[c.key]),
      color: (r: TableRow) => (i === 0 && c.kind === "text" ? "acc" : cellColor(c, r[c.key])),
    };
  });
}

/** `USE KEY=VALUE` arguments for the valuation functions: `ERP=5.5 G=2.5` -> {erp: "5.5", g: "2.5"}. */
export function keyValueArgs(args: string[]): { params: Record<string, string>; bad: string[] } {
  const params: Record<string, string> = {};
  const bad: string[] = [];
  for (const a of args) {
    const i = a.indexOf("=");
    if (i <= 0 || i === a.length - 1) bad.push(a);
    else params[a.slice(0, i).toLowerCase()] = a.slice(i + 1);
  }
  return { params, bad };
}
