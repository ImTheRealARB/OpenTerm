/**
 * Menu categories for GUI mode (pure: no React, no registry import, so vitest can load it anywhere).
 *
 * The GUI menu bar and sidebar group the ~100 functions in `registry.ts` under seven headings. This file is
 * the single place that says which function lives under which heading. `categories.test.ts` checks that every
 * registry code appears here exactly once and that nothing here is a stale code, so adding a function to the
 * registry without picking a category fails the tests (rather than silently missing from the GUI).
 */

export const CATEGORIES = ["Markets", "Charts", "News", "Research", "Portfolio", "Backtest", "Settings"] as const;
export type Category = (typeof CATEGORIES)[number];

/** code -> category. Keep it grouped by category so a reader can see what each menu holds. */
export const CATEGORY_OF: Readonly<Record<string, Category>> = Object.freeze({
  // Markets: quotes, boards, calendars, macro and crypto/commodity data, derivatives and rates screens
  Q: "Markets", QR: "Markets", WL: "Markets", WEI: "Markets", MOV: "Markets", EQS: "Markets", SECF: "Markets",
  FX: "Markets", FXC: "Markets", FXFA: "Markets", CRYP: "Markets", CDEP: "Markets", FUND: "Markets", LIQ: "Markets",
  STBL: "Markets", DEFI: "Markets", UNLK: "Markets", CMDTY: "Markets", NRG: "Markets", WETR: "Markets",
  RATES: "Markets", YAS: "Markets", SWPM: "Markets", CDSW: "Markets", CT: "Markets", WIRP: "Markets", COT: "Markets",
  ECO: "Markets", ERN: "Markets", IPO: "Markets", MACRO: "Markets", ECST: "Markets", WECO: "Markets",
  CENB: "Markets", PRED: "Markets",
  // Charts: anything that is mainly a picture of a time series or a map
  GP: "Charts", IND: "Charts", GIP: "Charts", HIST: "Charts", SEAS: "Charts", FRED: "Charts", IMAP: "Charts",
  // News: headlines and company events
  N: "News", CN: "News", EVTS: "News", BRIEF: "News",
  // Research: company fundamentals, ownership, valuation, options analytics, quant tools and the AI layer
  DES: "Research", FA: "Research", FIL: "Research", SEC: "Research", EE: "Research", EEO: "Research", ANR: "Research",
  MGMT: "Research", DVD: "Research", SPLT: "Research", CACS: "Research", SI: "Research", HDS: "Research",
  OWN: "Research", MGR: "Research", ETF: "Research", MEMB: "Research", COMP: "Research", CORR: "Research",
  REGIME: "Research", DCF: "Research", WACC: "Research", RV: "Research",
  OMON: "Research", PCR: "Research", OV: "Research", OSA: "Research", OVDV: "Research", SKEW: "Research", HIVG: "Research",
  FACT: "Research", QL: "Research", ALPHA: "Research",
  AI: "Research", SWARM: "Research", THESIS: "Research", AUDIT: "Research",
  // Portfolio: positions, alerts, risk and attribution
  PORT: "Portfolio", ALRT: "Portfolio", RISK: "Portfolio", OPT: "Portfolio", ATTR: "Portfolio",
  // Backtest: rule backtests and the data you bring to them
  BT: "Backtest", IMPORT: "Backtest",
  // Settings: help, preferences, layouts, keys, data sources and the other utilities
  HELP: "Settings", TMPL: "Settings", FUNC: "Settings", SHORTCUTS: "Settings", SETTINGS: "Settings", THEME: "Settings", APIKEYS: "Settings",
  SOURCES: "Settings", LOG: "Settings", PERF: "Settings", JOBS: "Settings", LAYOUT: "Settings", MONITOR: "Settings",
  KITE: "Settings", DLVR: "Settings",
});

/** The category a function code belongs to. Throws for an unmapped code: `categories.test.ts` keeps that impossible. */
export function categoryOf(code: string): Category {
  const c = CATEGORY_OF[code];
  if (!c) throw new Error(`no GUI category for function ${code}: add it to functions/categories.ts`);
  return c;
}

export interface CategoryItem {
  code: string;
  title: string;
}

/** Groups function definitions by category, in `CATEGORIES` order, each group sorted by code. */
export function groupByCategory<T extends CategoryItem>(items: readonly T[]): { category: Category; items: T[] }[] {
  return CATEGORIES.map((category) => ({
    category,
    items: items.filter((f) => CATEGORY_OF[f.code] === category).sort((a, b) => a.code.localeCompare(b.code)),
  }));
}
