/**
 * Payload types of the TRA (total return) and BETA routes (`/api/world/tra`, `/api/world/beta`; backend `world/returns.py`).
 * Type-only on purpose (no imports of the request layer), so the pure helpers in `functions/traBeta.ts` can be unit-tested in Node.
 * Percentages are already percentages (12.5 = 12.5 %), never fractions.
 */

/** One security's row in the TRA table (or the benchmark row). `error` set = the row has no numbers. */
export interface TraRow {
  symbol: string;
  source: string | null;
  error?: string;
  /** Dates (YYYY-MM-DD, exchange time zone) of the first and last bar used, and the calendar days between them. */
  first?: string;
  last?: string;
  days?: number;
  /** TOTAL = the source gave an adjusted close (dividends included); PRICE = price change only. */
  basis?: "TOTAL" | "PRICE";
  price_return_pct?: number;
  /** null for a PRICE-only row (no dividend data: never guessed). */
  total_return_pct?: number | null;
  dividend_part_pct?: number | null;
  /** Compound annual growth rate over `days` calendar days, from the total return (price return when PRICE only). */
  annualised_pct?: number | null;
  /** The benchmark's return over THIS row's dates, and the row's excess over it (not on the benchmark row). */
  bench_return_pct?: number | null;
  excess_pct?: number | null;
  excess_basis?: "TOTAL" | "PRICE" | null;
}

export interface TraChart {
  dates: string[];
  /** Both lines rebased to 100 on the first common date. */
  a: number[];
  b: number[];
  symbol_a: string;
  symbol_b: string;
  basis_a: "TOTAL" | "PRICE";
  basis_b: "TOTAL" | "PRICE";
}

export interface TraPayload {
  range: string;
  benchmark: TraRow;
  rows: TraRow[];
  warnings: string[];
  chart: TraChart | null;
}

export interface BetaPayload {
  symbol: string;
  benchmark: string;
  range: string;
  per: "D" | "W" | "M";
  periods_per_year: number;
  /** ADJUSTED CLOSES (dividends in) or RAW CLOSES (NO DIVIDENDS). */
  basis: string;
  first: string;
  last: string;
  /** Number of returns in the regression. */
  n: number;
  beta: number;
  /** 0.67 x raw + 0.33. */
  adj_beta: number;
  /** Intercept per period, and scaled up to a year (x periods per year); no risk-free rate. */
  alpha_pct: number;
  alpha_annual_pct: number;
  /** null when the security never moved. */
  r2: number | null;
  se_beta: number;
  /** Points in percent: x = benchmark return, y = security return. */
  scatter: { x: number[]; y: number[] };
  /** Beta over the trailing `win` returns, ending on each date. Empty when there are fewer returns than `win`. */
  rolling: { win: number; dates: string[]; beta: number[] };
  sources: Record<string, string>;
}
