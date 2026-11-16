/**
 * Command-line suggestions, grouped for display: a FUNCTIONS section and a SECURITIES section with a dim "More ..." row
 * when a section has more matches than fit. Pure and tiny (no registry import): CommandLine is in the startup bundle.
 *
 * Only the RENDERING changes. What gets suggested (the pipeline in CommandLine / cmdExtras) is untouched; this file turns the
 * flat list the pipeline produced into the rows to draw, and says which rows the keyboard can land on.
 *
 * Selection: `sel` in CommandLine is a position in `selectable` (the on-screen order, headers skipped), NOT an index into the
 * pipeline's list, because grouping can reorder it. Enter / Tab / click map back through the row, so the row highlighted on screen
 * is the row that is accepted.
 */
import type { Sector } from "./sectors";

export type Group = "FUNCTIONS" | "SECURITIES";

/** How many rows a group shows before its "More ..." row, and how many each "More ..." press adds. */
export const GROUP_CAP = 4;

/** Rows currently allowed per group. CommandLine keeps this in state and resets it whenever the typed text changes. */
export type Limits = Record<Group, number>;
export const defaultLimits = (): Limits => ({ FUNCTIONS: GROUP_CAP, SECURITIES: GROUP_CAP });

/** Anything with a `kind`: the real `Suggestion` type lives in the lazy chunk, so this file stays generic. */
interface HasKind {
  kind: string;
}

export type Row<S extends HasKind> =
  | { type: "header"; label: Group }
  | { type: "item"; s: S; pos: number }
  /** `hidden` = how many matches are still not shown; `pos` as for items. */
  | { type: "more"; group: Group; hidden: number; pos: number };

/** The rows a key or click can land on (everything but headers), in on-screen order. */
export type PickRow<S extends HasKind> = Exclude<Row<S>, { type: "header" }>;

export interface Grouped<S extends HasKind> {
  rows: Row<S>[];
  selectable: PickRow<S>[];
}

/** Which section a suggestion kind belongs to; the other kinds (NL, MEAN, ARG, LAYOUT, LIST) are not grouped. */
function groupOf(kind: string): Group | null {
  if (kind === "FUNC") return "FUNCTIONS";
  if (kind === "SEC" || kind === "RECENT") return "SECURITIES";
  return null;
}

export function groupSuggestions<S extends HasKind>(items: readonly S[], limits: Limits = defaultLimits()): Grouped<S> {
  const loose: S[] = []; // not grouped: keep their original order, listed first (NL / MEAN were first already)
  const byGroup: Record<Group, S[]> = { FUNCTIONS: [], SECURITIES: [] };
  const order: Group[] = []; // groups in the order the pipeline first produced them, so Tab still takes the pipeline's top pick
  for (const s of items) {
    const g = groupOf(s.kind);
    if (!g) loose.push(s);
    else {
      if (!byGroup[g].length) order.push(g);
      byGroup[g].push(s);
    }
  }

  const rows: Row<S>[] = [];
  const selectable: PickRow<S>[] = [];
  // Every pickable row gets its position in `selectable` (what the keyboard's `sel` counts).
  const addItem = (s: S) => {
    const row: PickRow<S> = { type: "item", s, pos: selectable.length };
    selectable.push(row);
    rows.push(row);
  };
  const addMore = (group: Group, hidden: number) => {
    const row: PickRow<S> = { type: "more", group, hidden, pos: selectable.length };
    selectable.push(row);
    rows.push(row);
  };

  for (const s of loose) addItem(s);
  for (const g of order) {
    rows.push({ type: "header", label: g });
    const all = byGroup[g];
    const shown = all.slice(0, limits[g]);
    for (const s of shown) addItem(s);
    if (all.length > shown.length) addMore(g, all.length - shown.length);
  }
  return { rows, selectable };
}

/** The new limits after "More ..." was chosen for a group: one more page. */
export function expand(limits: Limits, group: Group): Limits {
  return { ...limits, [group]: limits[group] + GROUP_CAP };
}

/** Text of a "More ..." row. */
export const moreLabel = (g: Group): string => (g === "FUNCTIONS" ? "More Functions..." : "More Securities...");

/** Title-case market-sector words, keyed by the grammar's sector names (command/sectors.ts). */
const SECTOR_TEXT: Readonly<Record<Sector, string>> = {
  EQUITY: "Equity",
  INDEX: "Index",
  CURNCY: "Curncy",
  COMDTY: "Comdty",
  GOVT: "Govt",
  CORP: "Corp",
  CRYPTO: "Crypto",
};

/** Yahoo yield indices (the same four that `GOVT_YIELDS` in sectors.ts maps to). */
const YIELD_INDEXES = new Set(["^IRX", "^FVX", "^TNX", "^TYX"]);
/** Quote currencies that make `XXX-<quote>` a crypto pair (BRK-B is a share class, not a pair). */
const CRYPTO_QUOTE = /^[A-Z0-9]{2,10}-(USD|USDT|USDC|EUR|GBP|INR|JPY|BTC|ETH)$/;

/**
 * The market-sector word shown dim at the right of a security row, worked out ONLY from the symbol's shape
 * (the same Yahoo-style shapes the sector grammar produces); "" when we cannot tell. Never a guess from the company name.
 */
export function sectorWord(symbol: string): string {
  const t = symbol.toUpperCase();
  if (YIELD_INDEXES.has(t)) return SECTOR_TEXT.GOVT;
  if (t.startsWith("^")) return SECTOR_TEXT.INDEX;
  if (/^[A-Z0-9]+=X$/.test(t)) return SECTOR_TEXT.CURNCY;
  if (/^[A-Z0-9]+=F$/.test(t)) return SECTOR_TEXT.COMDTY;
  if (CRYPTO_QUOTE.test(t)) return SECTOR_TEXT.CRYPTO;
  // A plain ticker, a share class (BRK-B) or one with an exchange suffix (RELIANCE.NS, VOD.L).
  if (/^[A-Z0-9]{1,10}([.-][A-Z0-9]{1,3})?$/.test(t)) return SECTOR_TEXT.EQUITY;
  return "";
}
