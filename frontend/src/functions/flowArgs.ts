/**
 * Pure helpers shared by the order flow panels TAS, BIGT and FOOT (no React, no request layer, so vitest can import it).
 *
 *   TAS  [SYMBOL]                         BTCUSDT TAS     TAS BTC-USDT
 *   BIGT [SYMBOL] [MIN=COINS|USD=AMOUNT]  BIGT BTCUSDT MIN=5     BIGT ETHUSDT USD=250K
 *   FOOT [SYMBOL] [INTERVAL] [BARS]       FOOT BTCUSDT 5M 40
 *
 * The symbol is whatever words are left after the options are taken out (joined, like CDEP does), else the panel's sticky security,
 * else BTCUSDT. The SERVER decides whether it is a Binance spot pair: anything else answers ORDER FLOW: CRYPTO ONLY (BINANCE SPOT PAIRS).
 *
 * TAS and FOOT also take REC=<session id>: a recorded session instead of live data (recArgs.ts).
 */
import { sessionId, splitRec } from "./recArgs";

export const FLOW_INTERVALS = ["1M", "3M", "5M", "15M", "30M", "1H"] as const;
export type FlowInterval = (typeof FLOW_INTERVALS)[number];
export const DEFAULT_SYMBOL = "BTCUSDT";
export const FOOT_BARS_DEFAULT = 30;
export const FOOT_BARS_MIN = 3;
export const FOOT_BARS_MAX = 120;

const SUFFIX: Record<string, number> = { K: 1e3, M: 1e6, B: 1e9 };

/** "250K" -> 250000, "1.5M" -> 1500000, "2B", "0.25" -> 0.25. null when it is not a positive number. */
export function parseAmount(text: string): number | null {
  const m = /^(\d+(?:\.\d+)?|\.\d+)([KMB])?$/i.exec(text.trim());
  if (!m) return null;
  const v = Number(m[1]) * (m[2] ? SUFFIX[m[2].toUpperCase()] : 1);
  return v > 0 ? v : null;
}

function symbolFrom(words: string[], sticky: string | undefined): string {
  return words.join("") || sticky?.toUpperCase() || DEFAULT_SYMBOL;
}

/** `REC=<id>` on TAS / FOOT: show a recorded session (see recArgs.ts). `rec` is the server's session id; `recError` a bad token. */
interface RecPart {
  rec?: string;
  recError?: string;
}

/** Takes the REC= token out of the words, lets `build` read the rest, then names the session for the symbol it found. */
function withRec<T extends { sym: string }>(words: string[], build: (rest: string[]) => T): T & RecPart {
  const { rest, stamp, recSym, bad } = splitRec(words);
  const out: T & RecPart = build(rest);
  if (stamp) out.rec = sessionId(out.sym, stamp, recSym);
  if (bad) out.recError = bad;
  return out;
}

export interface TasArgs extends RecPart {
  sym: string;
}

export function parseTasArgs(args: string[], sticky?: string): TasArgs {
  return withRec(args.filter(Boolean).map((w) => w.toUpperCase()), (rest) => ({ sym: symbolFrom(rest, sticky) }));
}

export interface BigtArgs {
  sym: string;
  /** coins; undefined = not given */
  min?: number;
  /** quote-currency amount (dollars for USD pairs); undefined = not given */
  usd?: number;
  /** a word that looked like MIN= / USD= but was not a positive number */
  error?: string;
}

export function parseBigtArgs(args: string[], sticky?: string): BigtArgs {
  const words: string[] = [];
  const out: BigtArgs = { sym: "" };
  for (const w of args.filter(Boolean).map((x) => x.toUpperCase())) {
    const opt = /^(MIN|USD)=(.*)$/.exec(w);
    if (!opt) {
      words.push(w);
      continue;
    }
    const v = parseAmount(opt[2]);
    if (v === null) out.error = `${opt[1]}= NEEDS A POSITIVE NUMBER (250, 0.5, 250K, 1.5M)`;
    else if (opt[1] === "MIN") out.min = v;
    else out.usd = v;
  }
  out.sym = symbolFrom(words, sticky);
  return out;
}

export interface FootArgs extends RecPart {
  sym: string;
  interval: FlowInterval;
  bars: number;
}

export function parseFootArgs(args: string[], sticky?: string): FootArgs {
  return withRec(args.filter(Boolean).map((x) => x.toUpperCase()), (rest) => {
    const words: string[] = [];
    let interval: FlowInterval = "1M";
    let bars = FOOT_BARS_DEFAULT;
    for (const w of rest) {
      if ((FLOW_INTERVALS as readonly string[]).includes(w)) interval = w as FlowInterval;
      else if (/^\d{1,3}$/.test(w)) bars = Math.min(FOOT_BARS_MAX, Math.max(FOOT_BARS_MIN, Number(w)));
      else words.push(w);
    }
    return { sym: symbolFrom(words, sticky), interval, bars };
  });
}

/** The server reads lowercase interval words ("1m"). */
export const serverInterval = (i: FlowInterval): string => i.toLowerCase();

/** UTC clock text of a trade time: "14:03:22.417". */
export function clockMs(ms: number): string {
  return new Date(ms).toISOString().slice(11, 23);
}

/** UTC "HH:MM" of a bar start. */
export function clockMin(ms: number): string {
  return new Date(ms).toISOString().slice(11, 16);
}

/** A coin quantity in few characters: 0.00036 -> "0.0004", 0.1148 -> "0.115", 12.345 -> "12.35", 234.5 -> "234.5", 12345 -> "12.3K". */
export function fmtQty(v: number): string {
  const a = Math.abs(v);
  if (a === 0) return "0";
  if (a >= 10_000) return `${(v / 1000).toFixed(1)}K`;
  if (a >= 100) return v.toFixed(1);
  if (a >= 10) return v.toFixed(2);
  if (a >= 0.001) return v.toFixed(3);
  return v.toFixed(4);
}

/** A signed quantity: "+3.500" / "-1.250" (delta rows). */
export const fmtSigned = (v: number): string => (v > 0 ? `+${fmtQty(v)}` : fmtQty(v));

/** What a BIGT filter says on screen: "AT LEAST 5 BTC" / "AT LEAST $100,000". */
export function filterText(f: { min_qty: number | null; usd: number | null }, base: string): string {
  const parts: string[] = [];
  if (f.min_qty !== null) parts.push(`${f.min_qty.toLocaleString("en-US")} ${base}`);
  if (f.usd !== null) parts.push(`$${f.usd.toLocaleString("en-US")}`);
  return `AT LEAST ${parts.join(" AND ")}`;
}
