import { TWINS } from "./aliases";

/**
 * Menu categories for GUI mode (pure: no React, no registry import, so vitest can load it anywhere).
 *
 * The GUI menu bar and sidebar group the ~120 functions in `registry.ts` in two levels:
 *   category (the seven menu-bar headings)  >  subgroup (a plain-word group, e.g. "Crypto")  >  function.
 * `MENU` below is the single place that says where each function lives. Everything else (the code -> category map,
 * the help drawer's "Category" line, the FUNC directory) is derived from it, so a function is placed exactly once.
 *
 * Rules the tests enforce (`categories.test.ts`):
 *  - every registry code appears in exactly one subgroup, or is a twin in `TWINS` (a twin shares its original's place);
 *  - at most 8 subgroups per category and at most 12 functions per subgroup, so no menu needs scrolling to be understood;
 *  - no stale codes.
 * Adding a function to the registry without placing it here fails the tests, rather than silently missing from the GUI.
 *
 * A category with a single subgroup (Charts, News, Portfolio, Backtest) is short enough to list its functions directly:
 * the menu shows no second level for it. Within a subgroup, functions are listed in the order written here (most used first).
 */

export const CATEGORIES = ["Markets", "Charts", "News", "Research", "Portfolio", "Backtest", "Settings"] as const;
export type Category = (typeof CATEGORIES)[number];

/** One plain-word group of functions inside a category. */
export interface Subgroup {
  name: string;
  codes: readonly string[];
}

/** Settings subgroups that also carry GUI-only rows (tour, welcome card, templates, font ...): see `gui/MenuBar.tsx`. */
export const SUB_HELP = "Help";
export const SUB_LOOK = "Look and layout";

/** category -> its subgroups, in menu order. */
export const MENU: Readonly<Record<Category, readonly Subgroup[]>> = {
  Markets: [
    { name: "Stocks and funds", codes: ["Q", "QR", "WL", "WEI", "MOV", "EQS", "SECF", "MF"] },
    { name: "Calendars", codes: ["ECO", "ERN", "IPO", "CENB"] },
    { name: "Currencies", codes: ["FX", "FXC", "FXFA"] },
    { name: "Crypto", codes: ["CRYP", "CDEP", "FUND", "LIQ", "STBL", "DEFI", "ADDR"] },
    { name: "Commodities and energy", codes: ["CMDTY", "NRG", "WETR", "CT", "COT"] },
    { name: "Rates and bonds", codes: ["RATES", "WIRP", "YAS", "SWPM", "CDSW"] },
    { name: "Economy", codes: ["MACRO", "USMAC", "WECO", "ECST", "DBSRCH", "TRADE", "PRED"] },
    { name: "Ships, flights and maps", codes: ["MAP", "SHIP", "PORTS", "AIS", "FLT"] },
  ],
  Charts: [{ name: "Charts", codes: ["GP", "IND", "GIP", "HIST", "SEAS", "IMAP", "FRED"] }],
  News: [{ name: "News", codes: ["HOME", "N", "CN", "EVTS", "BRIEF"] }],
  Research: [
    { name: "Company", codes: ["DES", "FA", "COMP", "MGMT", "DVD", "SPLT", "CACS"] },
    { name: "Analysts and valuation", codes: ["ANR", "EE", "EEO", "DCF", "WACC", "RV"] },
    { name: "Filings and owners", codes: ["FIL", "OWN", "HDS", "MGR", "SI", "ETF", "MEMB"] },
    { name: "Options", codes: ["OMON", "PCR", "OV", "OSA", "OVDV", "SKEW", "HIVG"] },
    { name: "Statistics", codes: ["CORR", "REGIME", "FACT", "QL", "ALPHA"] },
    { name: "AI research", codes: ["AI", "SWARM", "THESIS", "AUDIT"] },
    { name: "Public records", codes: ["FEDREG", "CONGRESS", "FEC", "USASP", "UKCO"] },
  ],
  Portfolio: [{ name: "Portfolio", codes: ["PORT", "ALRT", "RISK", "OPT", "ATTR"] }],
  Backtest: [{ name: "Backtest", codes: ["BT", "IMPORT"] }],
  Settings: [
    { name: SUB_HELP, codes: ["HELP", "FUNC", "SHORTCUTS"] },
    { name: SUB_LOOK, codes: ["SETTINGS", "THEME", "TAPE", "LAYOUT", "TMPL"] },
    { name: "Keys and connections", codes: ["APIKEYS", "SOURCES", "KITE", "DLVR"] },
    { name: "System", codes: ["JOBS", "PERF", "LOG"] },
  ],
};

/**
 * code -> category, derived from `MENU`. Twins (aliases.ts: SEC, MONITOR) only repeat another function: they work when typed and
 * share the original's category, but the menus and sidebar leave them out, since two rows for one thing only make a beginner choose.
 */
export const CATEGORY_OF: Readonly<Record<string, Category>> = Object.freeze(
  (() => {
    const out: Record<string, Category> = {};
    for (const c of CATEGORIES) for (const g of MENU[c]) for (const code of g.codes) out[code] = c;
    for (const [twin, original] of Object.entries(TWINS)) out[twin] = out[original];
    return out;
  })(),
);

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

/**
 * One category's menu: its subgroups, each with the function definitions it lists (in `MENU` order). Codes missing
 * from `defs` are skipped (the tests guarantee there are none in the real registry).
 */
export function menuOf<T extends CategoryItem>(category: Category, defs: readonly T[]): { name: string; items: T[] }[] {
  const byCode = new Map(defs.map((d) => [d.code, d]));
  return MENU[category].map((g) => ({ name: g.name, items: g.codes.map((c) => byCode.get(c)).filter((d): d is T => !!d) }));
}

/** Where a flyout (a menu's second level) goes: right of its row, or left when it would cross the window edge. Pure, for tests. */
export function flyoutPosition(
  row: { top: number; left: number; right: number },
  size: { width: number; height: number },
  viewport: { width: number; height: number },
): { top: number; left: number; flipped: boolean } {
  const flipped = row.right + size.width > viewport.width && row.left - size.width >= 0;
  const left = flipped ? row.left - size.width : row.right;
  // Keep the whole flyout on screen: a row near the bottom opens it upwards as far as needed.
  const top = Math.max(0, Math.min(row.top, viewport.height - size.height));
  return { top, left, flipped };
}
