/**
 * Portfolio P&L math. Pure, unit-tested directly.
 *
 * Mixed currencies: each row is valued in its own currency (the quote's), then converted to the portfolio base
 * with a live FX rate (Yahoo `CCYBASE=X`). Converted rows are labelled; a row whose rate is not known yet is left
 * out of the base totals and shown in a per-currency subtotal instead. Nothing is ever summed across currencies
 * without a rate.
 */

/** Minor-unit quote currencies (Yahoo): pence, cents, agorot -> (major currency, factor). */
const MINOR: Record<string, [string, number]> = { GBp: ["GBP", 0.01], GBX: ["GBP", 0.01], ZAc: ["ZAR", 0.01], ILA: ["ILS", 0.01] };

export const majorOf = (ccy: string): [string, number] => MINOR[ccy] ?? [ccy.toUpperCase(), 1];

/** The Yahoo FX symbol that converts `ccy` into `base`, or null when no conversion is needed. */
export function fxSymbol(ccy: string, base: string): string | null {
  const [major] = majorOf(ccy);
  return major === base ? null : `${major}${base}=X`;
}

export interface PosInput {
  symbol: string;
  qty: number;
  cost: number | null;
  /** Currency the position says it is in (optional, from the user or the CSV). */
  posCurrency: string | null;
  /** Currency of the quote (authoritative for price units), when known. */
  quoteCurrency: string | null;
  last: number | null;
  /** Change per unit vs previous close. */
  change: number | null;
}

export interface RowCalc {
  ccy: string | null;
  /** Position and quote disagree on currency: not valued in base. */
  mismatch: boolean;
  mv: number | null;
  day: number | null;
  unrl: number | null;
  unrlPct: number | null;
  /** Base-currency values; null when the price or the FX rate is missing. */
  mvBase: number | null;
  dayBase: number | null;
  unrlBase: number | null;
  costBase: number | null;
  /** Valued through an FX rate. */
  converted: boolean;
}

/** `rate(fxSymbol)` returns the live rate (base units per one major unit) or null. */
export function calcRow(p: PosInput, base: string, rate: (fx: string) => number | null): RowCalc {
  const mismatch = !!(p.posCurrency && p.quoteCurrency && majorOf(p.posCurrency)[0] !== majorOf(p.quoteCurrency)[0]);
  const ccy = p.quoteCurrency ?? p.posCurrency;
  const mv = p.last == null ? null : p.qty * p.last;
  const day = p.change == null ? null : p.qty * p.change;
  const unrl = p.last == null || p.cost == null ? null : p.qty * (p.last - p.cost);
  const basis = p.cost == null ? null : Math.abs(p.qty * p.cost);
  const unrlPct = unrl == null || !basis ? null : (unrl / basis) * 100;
  let factor: number | null = null;
  let converted = false;
  if (ccy && !mismatch) {
    const [, minor] = majorOf(ccy);
    const fx = fxSymbol(ccy, base);
    const r = fx ? rate(fx) : 1;
    if (r != null && Number.isFinite(r) && r > 0) factor = minor * r;
    converted = !!fx;
  }
  const toBase = (v: number | null) => (v == null || factor == null ? null : v * factor);
  return {
    ccy, mismatch, mv, day, unrl, unrlPct, converted,
    mvBase: toBase(mv), dayBase: toBase(day), unrlBase: toBase(unrl), costBase: toBase(basis),
  };
}

export interface Totals {
  base: string;
  mv: number;
  day: number;
  dayPct: number | null;
  unrl: number;
  unrlPct: number | null;
  cost: number;
  /** Sum of |market value| in base: the denominator of weights (so shorts do not shrink it). */
  gross: number;
  /** Major currencies converted into base for these totals. */
  converted: string[];
  /** Rows left out of the base totals, summed per currency (no FX rate yet, or a currency mismatch). */
  unconverted: { ccy: string; mv: number; day: number; unrl: number; count: number }[];
  /** Symbols without a price yet. */
  noPrice: string[];
}

export function totals(rows: { symbol: string; calc: RowCalc }[], base: string): Totals {
  const t: Totals = { base, mv: 0, day: 0, dayPct: null, unrl: 0, unrlPct: null, cost: 0, gross: 0, converted: [], unconverted: [], noPrice: [] };
  const conv = new Set<string>();
  const un = new Map<string, Totals["unconverted"][number]>();
  let dayDen = 0;
  let unrlCost = 0;
  for (const { symbol, calc: c } of rows) {
    if (c.mv == null) {
      t.noPrice.push(symbol);
      continue;
    }
    if (c.mvBase == null) {
      const key = c.mismatch ? `${c.ccy ?? "?"} (CCY MISMATCH)` : (c.ccy ?? "?");
      const u = un.get(key) ?? { ccy: key, mv: 0, day: 0, unrl: 0, count: 0 };
      u.mv += c.mv;
      u.day += c.day ?? 0;
      u.unrl += c.unrl ?? 0;
      u.count++;
      un.set(key, u);
      continue;
    }
    if (c.converted && c.ccy) conv.add(majorOf(c.ccy)[0]);
    t.mv += c.mvBase;
    t.gross += Math.abs(c.mvBase);
    if (c.dayBase != null) {
      t.day += c.dayBase;
      dayDen += c.mvBase - c.dayBase;
    }
    if (c.unrlBase != null && c.costBase != null) {
      t.unrl += c.unrlBase;
      t.cost += c.costBase;
      unrlCost += c.costBase;
    }
  }
  t.dayPct = dayDen ? (t.day / Math.abs(dayDen)) * 100 : null;
  t.unrlPct = unrlCost ? (t.unrl / unrlCost) * 100 : null;
  t.converted = [...conv].sort();
  t.unconverted = [...un.values()];
  return t;
}

/** Weight of a row in the base total (percent of gross exposure), or null when it is not valued in base. */
export const weight = (c: RowCalc, t: Totals): number | null => (c.mvBase == null || !t.gross ? null : (c.mvBase / t.gross) * 100);
