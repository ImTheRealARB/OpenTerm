/**
 * SECF fuzzy finder (pure): scores a query against symbol + name. Tiers, best first: exact symbol, symbol prefix, name starts with,
 * a name word starts with, text inside a word, subsequence, one typo (insert / delete / swap / replace). Every query word must score;
 * ties go to the larger market cap. The universe is the EQS screener table plus Yahoo search hits (non-US names live only there).
 */
import type { SearchHit } from "../net/api";
import type { Universe } from "./eqsFilter";

export interface Cand {
  symbol: string;
  name: string;
  exchange: string | null;
  type: string | null;
  sector: string | null;
  mcap: number | null;
  src: "EQS" | "SEARCH" | "BOTH";
}
export interface Hit extends Cand {
  score: number;
}

const WORD = /[^a-z0-9]+/;

/** True when `a` and `b` differ by at most one insertion, deletion, replacement or adjacent swap. */
export function withinOneEdit(a: string, b: string): boolean {
  if (a === b) return true;
  const la = a.length;
  const lb = b.length;
  if (Math.abs(la - lb) > 1) return false;
  let i = 0;
  while (i < la && i < lb && a[i] === b[i]) i++;
  if (la === lb) {
    if (a.slice(i + 1) === b.slice(i + 1)) return true; // one replacement
    return a[i] === b[i + 1] && a[i + 1] === b[i] && a.slice(i + 2) === b.slice(i + 2); // one swap
  }
  return la > lb ? a.slice(i + 1) === b.slice(i) : b.slice(i + 1) === a.slice(i);
}

function isSubsequence(t: string, s: string): boolean {
  let j = 0;
  for (let i = 0; i < s.length && j < t.length; i++) if (s[i] === t[j]) j++;
  return j === t.length;
}

interface Prepared {
  sym: string;
  words: string[];
  joined: string;
}
const prep = (c: { symbol: string; name: string }): Prepared => {
  const words = c.name.toLowerCase().split(WORD).filter(Boolean);
  return { sym: c.symbol.toLowerCase(), words, joined: words.join("") };
};

function tokenScore(t: string, p: Prepared): number {
  if (t === p.sym) return 1000;
  if (p.sym.startsWith(t)) return 900 - Math.min(50, p.sym.length - t.length);
  if (p.words[0]?.startsWith(t)) return 800;
  if (p.words.some((w) => w.startsWith(t))) return 700;
  if (p.words.join(" ").includes(t)) return 450;
  if (t.length >= 3 && isSubsequence(t, p.sym)) return 300;
  if (t.length >= 4 && isSubsequence(t, p.joined)) return 250;
  if (t.length >= 3 && p.sym.length >= 3 && withinOneEdit(t, p.sym)) return 220;
  if (t.length >= 4 && p.words.some((w) => withinOneEdit(t, w) || (w.length > t.length && withinOneEdit(t, w.slice(0, t.length))))) return 200;
  return 0;
}

export const queryTokens = (q: string) => q.toLowerCase().split(/\s+/).filter(Boolean);

/** 0 = no match. */
export function scoreOne(query: string, c: { symbol: string; name: string }): number {
  const tokens = queryTokens(query);
  if (!tokens.length) return 0;
  const p = prep(c);
  let sum = 0;
  for (const t of tokens) {
    const s = tokenScore(t, p);
    if (!s) return 0;
    sum += s;
  }
  const whole = tokens.join("");
  return sum / tokens.length + (whole === p.joined ? 100 : 0);
}

export function rank(cands: Cand[], query: string, limit = 200): Hit[] {
  const tokens = queryTokens(query);
  if (!tokens.length) return [];
  const hits: Hit[] = [];
  for (const c of cands) {
    const score = scoreOne(query, c);
    if (score > 0) hits.push({ ...c, score });
  }
  hits.sort((a, b) => b.score - a.score || (b.mcap ?? -1) - (a.mcap ?? -1) || a.symbol.length - b.symbol.length || (a.symbol < b.symbol ? -1 : 1));
  return hits.slice(0, limit);
}

export function candidatesFromUniverse(u: Universe): Cand[] {
  return u.rows.map((r) => ({
    symbol: r[0], name: r[1], exchange: null, type: null, sector: u.sectors[r[9]] || null, mcap: r[6], src: "EQS" as const,
  }));
}

/** Yahoo search hits joined to the universe: a symbol in both keeps the universe's market cap and sector and says BOTH. */
export function mergeSearch(cands: Cand[], hits: SearchHit[]): Cand[] {
  const bySym = new Map(cands.map((c) => [c.symbol, c]));
  const out = [...cands];
  for (const h of hits) {
    const known = bySym.get(h.symbol);
    if (known) {
      const i = out.indexOf(known);
      out[i] = { ...known, exchange: h.exchange ?? known.exchange, type: h.type ?? known.type, src: "BOTH" };
    } else {
      const c: Cand = { symbol: h.symbol, name: h.name ?? "", exchange: h.exchange, type: h.type, sector: null, mcap: null, src: "SEARCH" };
      bySym.set(h.symbol, c);
      out.push(c);
    }
  }
  return out;
}
