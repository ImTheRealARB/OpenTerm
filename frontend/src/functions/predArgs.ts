/** Pure helpers for PRED (no DOM, no network): argument parsing, source filter, probability / volume text and the chart series. */
import type { PredDetail, PredOutcome, PredRow } from "../net/types";

export const PRED_LABEL = "MARKET-IMPLIED PROBABILITY, NOT A FORECAST";
export type PredSrc = "all" | "polymarket" | "kalshi";
export const MAX_Q = 80;
export const PRED_USAGE = "PRED [TEXT ...] [SRC=POLY|KALSHI|ALL]   e.g. PRED fed · PRED bitcoin SRC=KALSHI · PRED";

export interface PredArgs {
  q: string;
  src: PredSrc;
  error: string | null;
}

const SRC_NAMES: Record<string, PredSrc> = { ALL: "all", POLY: "polymarket", POLYMARKET: "polymarket", KALSHI: "kalshi" };

/** `PRED <text words> [SRC=POLY|KALSHI|ALL]`: the words filter the questions (every word must appear); SRC keeps one source. */
export function parsePredArgs(args: string[]): PredArgs {
  let src: PredSrc = "all";
  const words: string[] = [];
  for (const raw of args.flatMap((a) => a.split(/\s+/)).filter(Boolean)) {
    const m = /^SRC=(.*)$/i.exec(raw);
    if (!m) {
      words.push(raw);
      continue;
    }
    const s = SRC_NAMES[m[1].toUpperCase()];
    if (!s) return { q: "", src: "all", error: `SRC MUST BE POLY, KALSHI OR ALL (GOT ${m[1].toUpperCase().slice(0, 12) || "NOTHING"})` };
    src = s;
  }
  return { q: words.join(" ").slice(0, MAX_Q).trim(), src, error: null };
}

export function filterSrc(rows: PredRow[], src: PredSrc): PredRow[] {
  return src === "all" ? rows : rows.filter((r) => r.source === src);
}

function scaled(v: number): string {
  if (!Number.isFinite(v)) return "";
  const a = Math.abs(v);
  if (a >= 1e9) return `${(v / 1e9).toFixed(1)}B`;
  if (a >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (a >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return v.toFixed(0);
}

/** Polymarket volume is US dollars, Kalshi's is contracts of US$1: the unit is always written out. */
export function fmtVolume(volume: number, unit: PredRow["vol_unit"]): string {
  return unit === "USD" ? `$${scaled(volume)}` : `${scaled(volume)} ct`;
}

export const fmtPct = (p: number | null | undefined): string => (p == null || !Number.isFinite(p) ? "" : `${(p * 100).toFixed(1)}%`);

/** The row's probability. A market whose lead outcome is not "Yes" (a team, a candidate) names it. */
export function fmtProb(r: Pick<PredRow, "prob" | "outcome">): string {
  const p = fmtPct(r.prob);
  return r.outcome.toLowerCase() === "yes" ? p : `${p} ${r.outcome.toUpperCase().slice(0, 10)}`;
}

export const sourceTag = (s: PredRow["source"]): string => (s === "polymarket" ? "POLYMARKET" : "KALSHI");

export function fmtOutcome(o: PredOutcome): string {
  const book = o.bid != null || o.ask != null ? `  BID ${fmtPct(o.bid) || "-"}  ASK ${fmtPct(o.ask) || "-"}` : "";
  return `${o.name.toUpperCase().padEnd(10)} ${(fmtPct(o.prob) || "NO PRICE").padStart(7)}${book}`;
}

export interface PredBars {
  symbol: string;
  interval: string;
  tz: string;
  t: Float64Array;
  o: Float64Array;
  h: Float64Array;
  l: Float64Array;
  c: Float64Array;
  v: Float64Array;
}

/** Probability history as a percent line (open = high = low = close). null when the source gave fewer than two points. */
export function predBars(d: Pick<PredDetail, "source" | "id" | "history">): PredBars | null {
  const h = d.history;
  if (!h || h.t.length < 2 || h.t.length !== h.p.length) return null;
  const c = Float64Array.from(h.p, (p) => p * 100);
  return { symbol: `${d.source}:${d.id}`, interval: "60m", tz: "UTC", t: Float64Array.from(h.t), o: c, h: c, l: c, c, v: new Float64Array(c.length) };
}
