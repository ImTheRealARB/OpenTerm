/**
 * Pure helpers for the Phase 7 macro functions (FRED, MACRO, RATES, ERN, ECO): argument parsing, date math and the
 * curve spreads. No imports from net/core or perf/metrics, so vitest can run it in Node.
 */

export const FRED_RANGES = ["1Y", "2Y", "5Y", "10Y", "20Y", "MAX"] as const;
export type FredRange = (typeof FRED_RANGES)[number];
export const FRED_DEFAULT_RANGE: FredRange = "5Y";
const SERIES_ID = /^[A-Z0-9_.]{1,40}$/;

export interface FredArgs {
  id: string | null;
  range: FredRange;
  /** Tokens that were neither the series nor a range (shown as a warning, never silently dropped). */
  ignored: string[];
}

/** FRED args: SERIES_ID and an optional range, in any order. `FRED UNRATE 10Y`, `FRED 10Y DGS10`. */
export function parseFredArgs(args: string[]): FredArgs {
  const out: FredArgs = { id: null, range: FRED_DEFAULT_RANGE, ignored: [] };
  for (const raw of args) {
    const a = raw.toUpperCase();
    if ((FRED_RANGES as readonly string[]).includes(a)) out.range = a as FredRange;
    else if (out.id === null && SERIES_ID.test(a)) out.id = a;
    else out.ignored.push(a);
  }
  return out;
}

/** MACRO args: everything is the search text. */
export const parseMacroArgs = (args: string[]): string => args.join(" ").replace(/\s+/g, " ").trim();

// --- dates (ISO strings; arithmetic in UTC so DST never shifts a day) --------------------------------------
const ISO = /^\d{4}-\d{2}-\d{2}$/;
export const isIsoDate = (s: string): boolean => ISO.test(s) && !Number.isNaN(Date.parse(`${s}T00:00:00Z`)) &&
  new Date(`${s}T00:00:00Z`).toISOString().slice(0, 10) === s;

export function addDays(iso: string, n: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

/** Today's date in New York (the market calendar's day). */
export function nyToday(now: Date = new Date()): string {
  const p = new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit" }).format(now);
  return p; // en-CA formats as YYYY-MM-DD
}

const DOW = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"];
const MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];

/** "FRI 16 OCT 2026". */
export function dayLabel(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`);
  return `${DOW[d.getUTCDay()]} ${String(d.getUTCDate()).padStart(2, "0")} ${MON[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}

export const isWeekend = (iso: string): boolean => [0, 6].includes(new Date(`${iso}T00:00:00Z`).getUTCDay());

export type ErnArgs = { ok: true; date: string } | { ok: false; error: string };

/** ERN args: nothing / TODAY, TOMORROW, YESTERDAY, +N / -N days, or YYYY-MM-DD. */
export function parseErnArgs(args: string[], today: string): ErnArgs {
  const a = (args[0] ?? "").toUpperCase();
  if (a === "" || a === "TODAY") return { ok: true, date: today };
  if (a === "TOMORROW") return { ok: true, date: addDays(today, 1) };
  if (a === "YESTERDAY") return { ok: true, date: addDays(today, -1) };
  if (/^[+-]\d{1,3}$/.test(a)) return { ok: true, date: addDays(today, Number(a)) };
  if (isIsoDate(a)) return { ok: true, date: a };
  return { ok: false, error: `BAD DATE ${a}. USE ERN [TODAY|TOMORROW|YESTERDAY|+N|-N|YYYY-MM-DD]` };
}

export interface EcoArgs {
  days: number;
  major: boolean;
  start: string | null;
  error: string | null;
}

export const ECO_WINDOWS = [7, 14, 30, 62] as const;

/** ECO args in any order: a window (`7`, `14D`, `30`), MAJOR, and an optional start date. */
export function parseEcoArgs(args: string[]): EcoArgs {
  const out: EcoArgs = { days: 14, major: false, start: null, error: null };
  for (const raw of args) {
    const a = raw.toUpperCase();
    const n = /^(\d{1,2})D?$/.exec(a);
    if (a === "MAJOR") out.major = true;
    else if (isIsoDate(a)) out.start = a;
    else if (n && Number(n[1]) >= 1 && Number(n[1]) <= 62) out.days = Number(n[1]);
    else out.error = `BAD ARGUMENT ${a}. USE ECO [1-62] [MAJOR] [YYYY-MM-DD]`;
  }
  return out;
}

// --- yield curve ------------------------------------------------------------------------------------------
/** Spread in basis points between two tenors (b minus a), or null when either is missing. */
export function spreadBp(tenors: string[], yields: (number | null)[], a: string, b: string): number | null {
  const ia = tenors.indexOf(a);
  const ib = tenors.indexOf(b);
  if (ia < 0 || ib < 0) return null;
  const ya = yields[ia];
  const yb = yields[ib];
  return ya == null || yb == null ? null : Math.round((yb - ya) * 100);
}

/** Change in basis points (now minus then); null when either side is missing. */
export const bpChange = (now: number | null | undefined, then: number | null | undefined): number | null =>
  now == null || then == null ? null : Math.round((now - then) * 100);

export const fmtBp = (v: number | null): string => (v == null ? "-" : `${v > 0 ? "+" : ""}${v}`);

/** FRED series id for a Treasury tenor label ("10Y" -> DGS10); null for tenors FRED does not carry (1.5M, 2M, 4M). */
export function fredIdForTenor(tenor: string): string | null {
  const ids: Record<string, string> = {
    "1M": "DGS1MO", "3M": "DGS3MO", "6M": "DGS6MO", "1Y": "DGS1", "2Y": "DGS2", "3Y": "DGS3", "5Y": "DGS5",
    "7Y": "DGS7", "10Y": "DGS10", "20Y": "DGS20", "30Y": "DGS30",
  };
  return ids[tenor] ?? null;
}

/** Text bar for a yield, scaled to `max` over `width` cells (a one-glyph minimum for positive yields). */
export function yieldBar(v: number | null, max: number, width: number): string {
  if (v == null || max <= 0 || v <= 0) return "";
  return "█".repeat(Math.max(1, Math.round((v / max) * width)));
}

/** Shape of the 2s10s spread: INVERTED below zero, FLAT within 10 bp, else NORMAL. */
export function curveShape(spread: number | null): "INVERTED" | "FLAT" | "NORMAL" | null {
  if (spread == null) return null;
  return spread < 0 ? "INVERTED" : spread < 10 ? "FLAT" : "NORMAL";
}

// --- FRED values ------------------------------------------------------------------------------------------
/** Value with decimals suited to its size (index 322.1, rate 4.20, GDP 32,563.03, sales 7.1e6). */
export function fmtSeriesValue(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "-";
  const a = Math.abs(v);
  const d = a >= 1e6 ? 0 : a >= 1000 ? 1 : a >= 0.01 ? 2 : 4;
  return v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
}

export const fmtSeriesChange = (v: number | null | undefined): string =>
  v == null || !Number.isFinite(v) ? "-" : (v > 0 ? "+" : "") + fmtSeriesValue(v);
