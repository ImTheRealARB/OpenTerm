/** JRNL, pure part (no React, no net): response types, argument parsing, number formats and the mapping text the import step edits. */

export type JrnlView = "TRIPS" | "STATS" | "FINDINGS" | "SHADOW" | "IMPORT";
export const VIEWS: readonly JrnlView[] = ["TRIPS", "STATS", "FINDINGS", "SHADOW", "IMPORT"];
export const BROKERS = ["auto", "zerodha", "ibkr", "alpaca", "generic"] as const;

export interface JrnlTrip {
  id: string; symbol: string; currency: string; side: "long" | "short"; qty: number;
  entry_time: string; exit_time: string; entry_price: number; exit_price: number;
  fees: number; pnl: number; pnl_pct: number; hold_s: number;
}
export interface JrnlGroup { key: string; n: number; pnl: number; win_rate: number }
export interface JrnlStats {
  n: number; wins?: number; losses?: number; flat?: number; win_rate?: number; avg_win?: number | null; avg_loss?: number | null;
  payoff?: number | null; expectancy?: number; profit_factor?: number | null; total_pnl?: number; gross_pnl?: number; fees?: number;
  best?: number; worst?: number; avg_hold_s?: number; median_hold_s?: number; avg_hold_win_s?: number | null; avg_hold_loss_s?: number | null;
  max_consec_losses?: number; max_consec_wins?: number; max_drawdown?: number; max_drawdown_end?: string | null;
  by_symbol?: JrnlGroup[]; by_weekday?: JrnlGroup[]; by_hour?: JrnlGroup[]; first?: string | null; last?: string | null;
}
export interface JrnlFinding {
  id: string; title: string; rule: string; status: "insufficient" | "clear" | "flagged"; severity: "none" | "watch" | "high"; plain: string;
  trips: { id: string; symbol: string; side: string; qty: number; entry_time: string; exit_time: string; pnl: number }[];
  trip_ids: string[];
}
export interface JrnlPosition { symbol: string; currency: string; side: string; qty: number; avg_price: number; since: string }
export interface JrnlAnalysis {
  empty: boolean; currency: string | null; currencies: { currency: string; fills: number; round_trips: number }[];
  stats?: JrnlStats; round_trips?: JrnlTrip[]; round_trips_total?: number; open_positions?: JrnlPosition[]; diagnostics?: JrnlFinding[];
  labels?: { note: string; times: string };
}
export interface JrnlSummary {
  fills: number; groups: { broker: string; currency: string; fills: number; first: string; last: string }[];
  imports: { id: number; at: number; broker: string; name: string; rows: number; added: number; duplicates: number; ignored: number }[];
}
export interface JrnlPreview { broker: string | null; columns: string[]; rows: number; mapping: Record<string, string>; sample: Record<string, string>[] }
export interface JrnlImportResult { import_id: number; broker: string; rows: number; added: number; duplicates: number; ignored: number; first: string; last: string }

export interface JrnlArgs { view: JrnlView; currency?: string; bad?: string }

/** `JRNL [TRIPS|STATS|FINDINGS|SHADOW|IMPORT] [CCY]`: the view and a 3-letter currency, in any order. */
export function parseArgs(args: string[]): JrnlArgs {
  let view: JrnlView = "TRIPS";
  let currency: string | undefined;
  for (const raw of args) {
    const a = raw.toUpperCase();
    if ((VIEWS as readonly string[]).includes(a)) view = a as JrnlView;
    else if (/^[A-Z]{3}$/.test(a) && !currency) currency = a;
    else return { view, currency, bad: `UNKNOWN ARGUMENT ${a}` };
  }
  return { view, currency };
}

export const fmtMoney = (x: number | null | undefined, digits = 2): string =>
  x == null || !Number.isFinite(x) ? "-" : `${x < 0 ? "-" : ""}${Math.abs(x).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
export const fmtPct = (x: number | null | undefined, digits = 1): string => (x == null || !Number.isFinite(x) ? "-" : `${(x * 100).toFixed(digits)}%`);
export const fmtRatio = (x: number | null | undefined): string => (x == null || !Number.isFinite(x) ? "-" : x.toFixed(2));

export function fmtDur(s: number | null | undefined): string {
  if (s == null || !Number.isFinite(s)) return "-";
  if (s < 90) return `${Math.round(s)}s`;
  if (s < 5400) return `${Math.round(s / 60)}m`;
  if (s < 172800) return `${(s / 3600).toFixed(1)}h`;
  return `${(s / 86400).toFixed(1)}d`;
}

/** The mapping the generic import needs, as one editable line: `time=When symbol=Ticker qty=Shares`. */
export const mappingToText = (m: Record<string, string>): string =>
  Object.entries(m).map(([k, v]) => `${k}=${v.includes(" ") ? JSON.stringify(v) : v}`).join(" ");

export function textToMapping(text: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const m of text.matchAll(/([a-z_]+)=("[^"]*"|\S+)/gi)) out[m[1].toLowerCase()] = m[2].replace(/^"|"$/g, "");
  return out;
}

export interface ImportForm { text: string; name: string; broker: string; mapping: string; dateOrder: string; currency: string }

/** The /api/journal/import body. The mapping goes along only for the generic format; a blank date order is not sent (slash dates are never guessed). */
export function importBody(f: ImportForm): Record<string, unknown> {
  const b: Record<string, unknown> = { text: f.text, name: f.name || "pasted", broker: f.broker, currency: f.currency.trim().toUpperCase() || "USD" };
  if (f.dateOrder) b.date_order = f.dateOrder;
  if (f.broker === "generic") {
    const m = textToMapping(f.mapping);
    if (Object.keys(m).length) b.mapping = m;
  }
  return b;
}

export const nextOf = <T,>(list: readonly T[], cur: T): T => list[(list.indexOf(cur) + 1) % list.length];
