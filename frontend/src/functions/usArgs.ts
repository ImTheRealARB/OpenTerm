/**
 * Pure helpers for TRADE (UN Comtrade) and USMAC (BLS, BEA, Census): argument parsing and number formats. No DOM, no network, so
 * vitest can run them (anything importing net/core cannot be unit-tested).
 */

export interface TradeArgs {
  reporter: string;
  partner: string;
  hs: string;
  years: number;
  error: string | null;
}

const TRADE_USAGE = "USAGE: TRADE <REPORTER> [<PARTNER>|WORLD] [TOTAL|<HS 2/4/6 DIGITS>] [<N>Y], FOR EXAMPLE TRADE USA CHN 85 8Y";

/** `TRADE USA CHN 8517 8Y`: reporter first; the other words are told apart by their shape (nY = years, digits or TOTAL = product, else partner). */
export function parseTradeArgs(args: string[]): TradeArgs {
  const w = args.filter(Boolean).map((a) => a.toUpperCase());
  const out: TradeArgs = { reporter: w[0] ?? "", partner: "", hs: "TOTAL", years: 5, error: null };
  if (!out.reporter) return { ...out, error: TRADE_USAGE };
  let partnerSet = false;
  for (const t of w.slice(1)) {
    const y = /^(\d{1,2})Y$/.exec(t);
    if (y) {
      out.years = Number(y[1]);
      if (out.years < 1 || out.years > 12) return { ...out, error: "YEARS MUST BE 1Y TO 12Y" };
    } else if (t === "TOTAL" || /^(\d{2}|\d{4}|\d{6})$/.test(t)) out.hs = t;
    else if (!partnerSet) {
      out.partner = t;
      partnerSet = true;
    } else return { ...out, error: `CANNOT READ ${t.slice(0, 16)}. ${TRADE_USAGE}` };
  }
  return out;
}

export type UsSource = "BLS" | "BEA" | "CENSUS";

export interface UsmacArgs {
  src: UsSource;
  q: string;
  /** True when one named series is asked for: the panel then opens straight on its history. */
  single: boolean;
  years: number;
  error: string | null;
}

const SOURCES: UsSource[] = ["BLS", "BEA", "CENSUS"];

/** `USMAC BLS CPI UNEMP`, `USMAC BEA GDPG`, `USMAC CENSUS TRADE CHINA 85`. No source = BLS. The server validates the words. */
export function parseUsmacArgs(args: string[]): UsmacArgs {
  const w = args.filter(Boolean).map((a) => a.toUpperCase());
  let src: UsSource = "BLS";
  if (w.length && (SOURCES as string[]).includes(w[0])) src = w.shift() as UsSource;
  else if (w.length && /^(BLS|BEA|CENSUS)/.test(w[0])) return { src, q: "", single: false, years: 3, error: `UNKNOWN SOURCE ${w[0].slice(0, 12)}. USE: ${SOURCES.join(" ")}` };
  const single = src === "BLS" ? w.length === 1 : src === "BEA" ? w.length === 1 && w[0] !== "INDUSTRY" : false;
  return { src, q: w.join(" "), single, years: single && src === "BLS" ? 10 : 3, error: null };
}

/** 1234567.8 -> "1,234,568"; small numbers keep decimals so a 4.3 % rate is not rounded to 4. */
export function fmtNum(v: number | null, digits?: number): string {
  if (v == null) return "";
  const d = digits ?? (Math.abs(v) >= 1000 ? 0 : Math.abs(v) >= 100 ? 1 : 2);
  return v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
}

export function fmtSigned(v: number | null, digits = 2): string {
  return v == null ? "" : (v > 0 ? "+" : "") + fmtNum(v, digits);
}

/** The kind of a USMAC series (mirrors `UsSeries["kind"]` in net/types.ts; redeclared here because this file must stay free of
 *  `net/core`, which vitest cannot import; a type-only import from net/types would also do). */
export type SeriesKind = "level" | "rate" | "unknown";

/**
 * How a change between two periods is written, per kind of series:
 *   level   -> "+3.00" and "+1.00%"      (an amount or index: a percent change makes sense)
 *   rate    -> "+1.20 pp" and ""         (the value is itself a percentage: a change is a difference in percentage POINTS;
 *                                         "3.4 vs 2.2 = +54.55%" would mislead)
 *   unknown -> "+1.20" and ""            (we do not know what the numbers are, so no percent and no "pp" claim)
 * `pct` is the backend's `chg_pct`, or computed from the two points on a history row; it is ignored unless the kind is "level".
 */
export function fmtChange(kind: SeriesKind, chg: number | null, pct: number | null): { chg: string; pct: string } {
  return {
    chg: chg == null ? "" : fmtSigned(chg) + (kind === "rate" ? " pp" : ""),
    pct: kind === "level" && pct != null ? fmtSigned(pct) + "%" : "",
  };
}

/** US dollars as billions (or millions below one billion) so the columns stay narrow: 1.2e11 -> "120.00B". */
export function fmtUsd(v: number | null): string {
  if (v == null) return "";
  const a = Math.abs(v);
  return a >= 1e9 ? `${(v / 1e9).toFixed(2)}B` : `${(v / 1e6).toFixed(1)}M`;
}

export function signColor(v: number | null): "up" | "down" | "dim" {
  return v == null || v === 0 ? "dim" : v > 0 ? "up" : "down";
}
