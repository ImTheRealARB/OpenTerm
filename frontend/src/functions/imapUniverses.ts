/**
 * What IMAP can map (pure, unit-tested). The heat map itself (ImapBoard.tsx) draws one thing: rows with a size, a colour value and a
 * group. Each universe turns its own data into that shape here:
 *
 *   US      the EQS screener universe (imapData.ts `buildImap`, adapted by `usView`)   IMAP [SECTOR|INDUSTRY|COUNTRY] ...
 *   CRYPTO  the crypto board (CoinGecko): size = market cap, colour = 24 hour change    IMAP CRYPTO [N=50]
 *   ETF     the FSRC table: size = total assets, colour = the day's % change (quotes)   IMAP ETF [N=150] [FSRC filter: FEE<0.2 CAT=TECH]
 *
 * To add a universe: a word in UNIVERSES, a builder here, and a small data component in IMAP.tsx that loads it.
 */
import type { FsrcRow } from "../net/etfTypes";
import type { Coin } from "../net/types";
import type { ImapData } from "./imapData";
import type { TGroup } from "./treemap";

export type ImapUniverse = "US" | "CRYPTO" | "ETF";
const UNIVERSES = new Set<string>(["CRYPTO", "ETF"]); // "US" is what you get when no universe word is typed

/** One tile's facts. `id` of a tile = the row's index in the view. */
export interface ImapRow {
  sym: string;
  name: string;
  /** Colour value: % change on the day (null = no value, drawn in the neutral colour and never invented). */
  pct: number | null;
  /** Tile size: market cap or total assets, always > 0 (rows without one have no tile). */
  size: number;
  group: string;
  /** What Enter opens in Q. */
  open: string;
  /** Extra readout text, e.g. "FEE 0.03%". */
  extra: string;
}

export interface ImapView {
  rows: ImapRow[];
  groups: TGroup[];
  /** Rows that qualified but have no size, so no tile. */
  noSize: number;
  /** Rows with a size left out by the N limit. */
  cut: number;
  /** Rows offered to the map before the size and N rules. */
  total: number;
}

export const CRYPTO_LIMIT = 50; // the crypto board lists the top 50
export const ETF_LIMIT = 150;
export const ETF_MAX = 200; // the quote endpoint takes at most 200 symbols a call

/** `IMAP CRYPTO N=20` -> CRYPTO and ["N=20"]. Without a universe word the map is the US equity one. */
export function parseUniverse(args: string[]): { universe: ImapUniverse; rest: string[] } {
  const i = args.findIndex((a) => UNIVERSES.has(a.toUpperCase()));
  if (i < 0) return { universe: "US", rest: args };
  return { universe: args[i].toUpperCase() as ImapUniverse, rest: args.filter((_, j) => j !== i) };
}

/** Takes `N=<count>` out of the words (capped at `max`; N=0 or junk keeps the default). */
export function takeLimit(args: string[], dflt: number, max: number): { limit: number; rest: string[] } {
  let limit = dflt;
  const rest: string[] = [];
  for (const a of args) {
    if (/^N=\d+$/i.test(a)) limit = Math.min(max, Number(a.slice(2)) || dflt);
    else rest.push(a);
  }
  return { limit, rest };
}

const bySizeDesc = (a: { size: number }, b: { size: number }) => b.size - a.size;

/** Groups rows (already sorted largest first) into treemap groups, the biggest group first. */
function groupRows(rows: ImapRow[]): TGroup[] {
  const byKey = new Map<string, TGroup>();
  rows.forEach((r, id) => {
    let g = byKey.get(r.group);
    if (!g) byKey.set(r.group, (g = { key: r.group, items: [] }));
    g.items.push({ id, value: r.size });
  });
  const total = (g: TGroup) => g.items.reduce((s, it) => s + it.value, 0);
  return [...byKey.values()].sort((a, b) => total(b) - total(a));
}

/** The US map in the shared shape. `data` is what `buildImap` returned; its groups say which group each row sits in. */
export function usView(data: ImapData): ImapView {
  const groupOf: string[] = [];
  for (const g of data.groups) for (const it of g.items) groupOf[it.id] = g.key;
  const rows = data.rows.map((r, id) => ({
    sym: r[0], name: r[1], pct: r[4], size: r[6]!, group: groupOf[id] ?? "UNCLASSIFIED", open: r[0], extra: "",
  }));
  return { rows, groups: data.groups, noSize: data.noCap, cut: data.cut, total: data.total };
}

/** The crypto map: one group (the board has no sectors), size = market cap. A coin with no market cap has no tile, and is counted. */
export function buildCrypto(coins: Coin[], limit: number): ImapView {
  const sized = coins.filter((c) => c.market_cap != null && c.market_cap > 0);
  const kept: ImapRow[] = sized
    .map((c) => ({
      sym: c.symbol, name: c.name ?? c.symbol, pct: c.change_pct_24h, size: c.market_cap!, group: "CRYPTO",
      open: `${c.symbol}-USD`, extra: c.rank != null ? `RANK ${c.rank}` : "",
    }))
    .sort(bySizeDesc)
    .slice(0, limit);
  return { rows: kept, groups: groupRows(kept), noSize: coins.length - sized.length, cut: sized.length - kept.length, total: coins.length };
}

/** The `limit` biggest funds by total assets (a fund with no total assets has no size, so it is not offered). */
export function topFunds(funds: FsrcRow[], limit: number): FsrcRow[] {
  return funds.filter((f) => f[3] != null && f[3] > 0).sort((a, b) => b[3]! - a[3]!).slice(0, limit);
}

/**
 * The ETF map: tiles are the biggest funds, grouped by category, sized by total assets. `pct` maps a symbol to today's % change;
 * a fund with no quote yet is drawn in the neutral colour (null), never given a made-up change.
 */
export function buildEtf(funds: FsrcRow[], pct: ReadonlyMap<string, number | null>, limit: number): ImapView {
  const kept: ImapRow[] = topFunds(funds, limit).map((f) => ({
    sym: f[0], name: f[1], pct: pct.get(f[0]) ?? null, size: f[3]!, group: f[4] ?? "UNCATEGORISED", open: f[0],
    extra: f[2] != null ? `FEE ${f[2].toFixed(f[2] < 0.1 ? 3 : 2)}%` : "",
  }));
  const sized = funds.filter((f) => f[3] != null && f[3] > 0).length;
  return { rows: kept, groups: groupRows(kept), noSize: funds.length - sized, cut: sized - kept.length, total: funds.length };
}
