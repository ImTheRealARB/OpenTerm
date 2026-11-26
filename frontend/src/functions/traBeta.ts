/**
 * TRA and BETA command arguments (pure: no store, no network, so vitest can run it) and the small formatting helpers
 * their panels share. The maths is on the server (`backend/openterm/world/returns.py`); this file only reads what was typed.
 *
 *   TRA AAPL 5Y                       one security over 5 years against the default benchmark (SPY)
 *   TRA AAPL,MSFT,NVDA 3Y VS ^NSEI    a list (commas or spaces), its own benchmark
 *   BETA AAPL                         beta over 2 years of daily returns against SPY
 *   BETA AAPL VS QQQ 5Y W WIN=26      weekly returns, a rolling window of 26 weekly returns
 */

import type { BarData } from "../chart/chartBase";

export const RETURN_RANGES = ["1M", "3M", "6M", "YTD", "1Y", "2Y", "3Y", "5Y", "10Y", "20Y", "MAX"] as const;
const RANGE_SET: ReadonlySet<string> = new Set(RETURN_RANGES);

export const DEFAULT_BENCHMARK = "SPY";
/** TRA is at most this many securities (the server pays one history request each). Mirrors `returnssvc.MAX_SYMBOLS`. */
export const TRA_MAX_SYMBOLS = 12;
export const BETA_PERIODS = ["D", "W", "M"] as const;
export type BetaPeriod = (typeof BETA_PERIODS)[number];
export const DEFAULT_WIN = 60;
/** Rolling window limits. Mirror the route's `win` query bounds in `world_routes.py`. */
export const WIN_MIN = 5;
export const WIN_MAX = 1000;

const tokens = (args: string[]): string[] =>
  args.flatMap((a) => a.split(",")).map((a) => a.trim().toUpperCase()).filter(Boolean);

export interface TraArgs {
  symbols: string[];
  vs: string;
  range: string;
  error: string | null;
}

/** `TRA SYM[,SYM...] [RANGE] [VS BENCHMARK]`. With no symbol typed, the panel's own security (`sticky`) is used if it has one. */
export function parseTraArgs(args: string[], sticky?: string): TraArgs {
  let range = "1Y";
  let vs = DEFAULT_BENCHMARK;
  const symbols: string[] = [];
  const t = tokens(args);
  for (let i = 0; i < t.length; i++) {
    if (t[i] === "VS") {
      if (!t[i + 1]) return { symbols, vs, range, error: "VS NEEDS A BENCHMARK, E.G. TRA AAPL 5Y VS QQQ" };
      vs = t[++i];
    } else if (RANGE_SET.has(t[i])) range = t[i];
    else if (!symbols.includes(t[i])) symbols.push(t[i]);
  }
  if (!symbols.length && sticky) symbols.push(sticky.toUpperCase());
  const error = !symbols.length
    ? "USAGE: TRA SYM[,SYM...] [1M..MAX] [VS BENCHMARK]  E.G. TRA AAPL,MSFT 3Y VS QQQ"
    : symbols.length > TRA_MAX_SYMBOLS ? `AT MOST ${TRA_MAX_SYMBOLS} SYMBOLS` : null;
  return { symbols, vs, range, error };
}

export interface BetaArgs {
  symbol: string;
  vs: string;
  range: string;
  per: BetaPeriod;
  win: number;
  error: string | null;
}

/**
 * `BETA SYM [VS BENCHMARK] [RANGE] [D|W|M] [WIN=n]`. The letters D, W and M are also tickers, so a lone D / W / M is the return period
 * only when a security is already known (typed earlier, or the panel's own); otherwise it is the security.
 */
export function parseBetaArgs(args: string[], sticky?: string): BetaArgs {
  let range = "2Y";
  let vs = DEFAULT_BENCHMARK;
  let per: BetaPeriod = "D";
  let win = DEFAULT_WIN;
  let symbol: string | null = null;
  const fail = (error: string): BetaArgs => ({ symbol: symbol ?? "", vs, range, per, win, error });
  const t = tokens(args);
  for (let i = 0; i < t.length; i++) {
    const tok = t[i];
    const w = /^WIN=(\d+)$/.exec(tok);
    if (tok === "VS") {
      if (!t[i + 1]) return fail("VS NEEDS A BENCHMARK, E.G. BETA AAPL VS QQQ");
      vs = t[++i];
    } else if (w) {
      win = Number(w[1]);
      if (win < WIN_MIN || win > WIN_MAX) return fail(`WIN MUST BE ${WIN_MIN} TO ${WIN_MAX} RETURNS`);
    } else if (RANGE_SET.has(tok)) range = tok;
    else if ((BETA_PERIODS as readonly string[]).includes(tok) && (symbol !== null || sticky)) per = tok as BetaPeriod;
    else if (symbol === null) symbol = tok;
    else return fail(`BETA TAKES ONE SECURITY: ${symbol} AND ${tok}`);
  }
  symbol ??= sticky?.toUpperCase() ?? null;
  if (!symbol) return fail("USAGE: BETA SYM [VS BENCHMARK] [1M..MAX] [D|W|M] [WIN=60]  E.G. BETA AAPL VS QQQ 5Y W");
  return { symbol, vs, range, per, win, error: null };
}

/** The word for a return period in the panel line. */
export const PERIOD_WORD: Record<BetaPeriod, string> = { D: "DAILY", W: "WEEKLY", M: "MONTHLY" };

/** A number with a fixed number of decimals, or a dash. */
export const num = (v: number | null | undefined, digits = 2): string => (v == null || !Number.isFinite(v) ? "—" : v.toFixed(digits));

// ---------- helpers shared by the TRA and BETA panels (pure, so vitest can run them) ----------

/** The next return period when the user presses P: D, then W, then M, then back to D. */
export const nextPeriod = (p: BetaPeriod): BetaPeriod => BETA_PERIODS[(BETA_PERIODS.indexOf(p) + 1) % BETA_PERIODS.length];

/** The next range in the list (TRA's R key), wrapping round. An unknown range starts at the first. */
export const nextRange = (r: string): string => {
  const i = (RETURN_RANGES as readonly string[]).indexOf(r);
  return RETURN_RANGES[(i + 1) % RETURN_RANGES.length];
};

/**
 * The args a BETA view is saved with after a key press changed one setting. The security itself lives on the panel, so it is not
 * repeated here; every other setting is written out, so a reloaded layout shows exactly what was on screen.
 */
export const betaViewArgs = (a: Pick<BetaArgs, "vs" | "range" | "per" | "win">): string[] => ["VS", a.vs, a.range, a.per, `WIN=${a.win}`];

/** The same for TRA: the symbols are args here (a list), so they are written out too. */
export const traViewArgs = (a: Pick<TraArgs, "symbols" | "vs" | "range">): string[] => [a.symbols.join(","), a.range, "VS", a.vs];

/** "YYYY-MM-DD" as epoch seconds at 00:00 UTC (the chart library wants epoch seconds). NaN for a malformed date. */
export const dayToEpoch = (d: string): number => {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(d);
  return m ? Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])) / 1000 : NaN;
};

/**
 * A dated series (rolling beta, rebased return lines) as chart bars (open = high = low = close). The server sends dates as text and
 * the chart wants typed arrays of epoch seconds; points with a bad date or a non-finite value are dropped, never filled in.
 */
export function datedBars(symbol: string, dates: string[], values: number[]): BarData {
  const keep: number[] = [];
  for (let i = 0; i < dates.length; i++) if (Number.isFinite(dayToEpoch(dates[i])) && Number.isFinite(values[i])) keep.push(i);
  const c = Float64Array.from(keep, (i) => values[i]);
  return { symbol, interval: "1d", tz: "UTC", t: Float64Array.from(keep, (i) => dayToEpoch(dates[i])), o: c, h: c, l: c, c, v: new Float64Array(keep.length) };
}

/** The plotted box of the BETA scatter: a little padding round the data, and always including zero so both axes' crossing is visible. */
export interface ScatterBox {
  xMin: number;
  xMax: number;
  yMin: number;
  yMax: number;
}

export function scatterBox(x: number[], y: number[]): ScatterBox | null {
  const xs = x.filter(Number.isFinite);
  const ys = y.filter(Number.isFinite);
  if (!xs.length || !ys.length) return null;
  const pad = (lo: number, hi: number): [number, number] => {
    const lo0 = Math.min(lo, 0);
    const hi0 = Math.max(hi, 0);
    const p = (hi0 - lo0 || 1) * 0.05;
    return [lo0 - p, hi0 + p];
  };
  const [xMin, xMax] = pad(Math.min(...xs), Math.max(...xs));
  const [yMin, yMax] = pad(Math.min(...ys), Math.max(...ys));
  return { xMin, xMax, yMin, yMax };
}

/** The fitted line y = alpha + beta x, as its two end points across the box's x range (percent units, like the points). */
export const fitLine = (box: ScatterBox, alphaPct: number, beta: number): [[number, number], [number, number]] => [
  [box.xMin, alphaPct + beta * box.xMin],
  [box.xMax, alphaPct + beta * box.xMax],
];

/** A signed percentage text, e.g. +12.34%. */
export const signedPct = (v: number | null | undefined, digits = 2): string =>
  v == null || !Number.isFinite(v) ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(digits)}%`;

/** The colour class of a return: up, down or neutral (a dash stays dim). */
export const signClass = (v: number | null | undefined): "up" | "down" | "dim" => (v == null || !Number.isFinite(v) ? "dim" : v >= 0 ? "up" : "down");
