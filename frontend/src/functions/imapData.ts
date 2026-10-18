/**
 * IMAP data preparation (pure): the EQS screener universe, filtered with the EQS grammar, grouped, sized by market cap.
 * `IMAP [SECTOR|INDUSTRY|COUNTRY] [N=3000] [EQS filter tokens]`.
 */
import { screen, type ParsedFilter, type Universe, type UniverseRow } from "./eqsFilter";
import type { TGroup } from "./treemap";

export type GroupBy = "SECTOR" | "INDUSTRY" | "COUNTRY";
export const DEFAULT_LIMIT = 3000;
export const MAX_LIMIT = 5000;
const BY_WORDS = new Set<string>(["SECTOR", "INDUSTRY", "COUNTRY"]);

export interface ImapOpts {
  by: GroupBy;
  limit: number;
}

export function parseImapArgs(args: string[]): ImapOpts & { rest: string[] } {
  let by: GroupBy = "SECTOR";
  let limit = DEFAULT_LIMIT;
  const rest: string[] = [];
  for (const a of args) {
    const u = a.toUpperCase();
    if (BY_WORDS.has(u)) by = u as GroupBy;
    else if (u.startsWith("BY=") && BY_WORDS.has(u.slice(3))) by = u.slice(3) as GroupBy;
    else if (/^N=\d+$/.test(u)) limit = Math.min(MAX_LIMIT, Number(u.slice(2)) || DEFAULT_LIMIT);
    else rest.push(a);
  }
  return { by, limit, rest };
}

export interface ImapData {
  /** The tiles' rows (`id` of a tile is an index into this array). */
  rows: UniverseRow[];
  groups: TGroup[];
  /** Rows that passed the filter but have no market cap, so no tile. */
  noCap: number;
  /** Rows with a market cap left out by the N limit. */
  cut: number;
  /** Rows that passed the filter. */
  total: number;
}

const FIELD = { SECTOR: 9, INDUSTRY: 10, COUNTRY: 7 } as const;

export function buildImap(u: Universe, filter: ParsedFilter, opts: ImapOpts): ImapData {
  const passed = screen(u, filter).rows;
  const withCap = passed.filter((r) => r[6] != null && r[6] > 0);
  const noCap = passed.length - withCap.length;
  withCap.sort((a, b) => b[6]! - a[6]!);
  const kept = withCap.slice(0, opts.limit);
  const table = opts.by === "SECTOR" ? u.sectors : opts.by === "INDUSTRY" ? u.industries : u.countries;
  const col = FIELD[opts.by];
  const byKey = new Map<string, TGroup>();
  kept.forEach((r, id) => {
    const key = table[r[col] as number] || "UNCLASSIFIED";
    let g = byKey.get(key);
    if (!g) byKey.set(key, (g = { key, items: [] }));
    g.items.push({ id, value: r[6]! });
  });
  const size = (g: TGroup) => g.items.reduce((s, it) => s + it.value, 0);
  const groups = [...byKey.values()].sort((a, b) => size(b) - size(a));
  return { rows: kept, groups, noCap, cut: withCap.length - kept.length, total: passed.length };
}
