/**
 * Company-name search for the GUI (pure: no React, no network, so vitest can test it).
 *
 * The data is the screener universe: one row per US stock, `[symbol, name, mcap]` is all we need here.
 * (`mcap` = market capitalisation = share price x number of shares; we use it only to put big companies first.)
 * Typing "apple" should suggest "AAPL  Apple Inc."; typing "aap" should too (symbol prefix).
 */

/** The three columns of a screener row this file reads. */
export interface UniverseEntry {
  symbol: string;
  name: string;
  mcap: number | null;
}

/** One suggestion shown under the search box. `via` says which text matched (the box uses it to decide what Enter does). */
export interface CompanyHit {
  symbol: string;
  /** Short display name, e.g. "Apple Inc." */
  name: string;
  via: "symbol" | "name";
}

/** Nasdaq names end in legal/share-class words ("Apple Inc. Common Stock"); a beginner does not need them. */
const SHARE_CLASS_TAIL = /\s+(common stock|common shares|ordinary shares?|class [a-z] (common stock|ordinary shares?)|american depositary shares?.*|depositary shares?.*)$/i;

/** "Apple Inc. Common Stock" -> "Apple Inc." */
export function cleanName(name: string): string {
  return name.replace(SHARE_CLASS_TAIL, "").trim();
}

/** Lower-case, drop punctuation so "Tesla, Inc." and "tesla inc" compare equal. */
const norm = (s: string): string => s.toLowerCase().replace(/[^a-z0-9 ]+/g, " ").replace(/\s+/g, " ").trim();

/**
 * Score one company for a query; 0 = no match. Higher is better:
 *   exact ticker 1000 > ticker prefix 800 > name starts with query 700 > a word of the name starts with it 600 > name contains it 300.
 */
function score(q: string, e: UniverseEntry, nameN: string): { s: number; via: "symbol" | "name" } {
  const sym = e.symbol.toLowerCase();
  if (sym === q) return { s: 1000, via: "symbol" };
  if (sym.startsWith(q)) return { s: 800 - sym.length, via: "symbol" };
  if (nameN.startsWith(q)) return { s: 700, via: "name" };
  if (nameN.includes(" " + q)) return { s: 600, via: "name" };
  if (q.length >= 3 && nameN.includes(q)) return { s: 300, via: "name" };
  return { s: 0, via: "name" };
}

/** Best matches for `query`, best first (ties: bigger company first). Empty for a blank query. */
export function matchCompanies(query: string, universe: readonly UniverseEntry[], limit = 6): CompanyHit[] {
  const q = norm(query);
  if (!q) return [];
  const scored: { e: UniverseEntry; s: number; via: "symbol" | "name" }[] = [];
  for (const e of universe) {
    const r = score(q, e, norm(e.name));
    if (r.s > 0) scored.push({ e, ...r });
  }
  scored.sort((a, b) => b.s - a.s || (b.e.mcap ?? 0) - (a.e.mcap ?? 0));
  return scored.slice(0, limit).map((x) => ({ symbol: x.e.symbol, name: cleanName(x.e.name), via: x.via }));
}

/** The set of two-letter pieces of a string ("tesla" -> te, es, sl, la); used to rate how alike two spellings are. */
function bigrams(s: string): Set<string> {
  const out = new Set<string>();
  for (let i = 0; i < s.length - 1; i++) out.add(s.slice(i, i + 2));
  return out;
}

/**
 * "Did you mean...": companies whose ticker or name looks most like `query` (shared two-letter pieces), used when a typed
 * symbol has no data. If nothing looks alike, falls back to the biggest companies so the user always has a next step.
 */
export function closestCompanies(query: string, universe: readonly UniverseEntry[], limit = 3): CompanyHit[] {
  const q = norm(query);
  const qb = bigrams(q);
  const scored: { e: UniverseEntry; s: number }[] = [];
  for (const e of universe) {
    let s = 0;
    for (const g of bigrams(e.symbol.toLowerCase())) if (qb.has(g)) s += 2; // a ticker piece counts double
    for (const g of bigrams(norm(e.name))) if (qb.has(g)) s += 1;
    if (s > 0) scored.push({ e, s });
  }
  const pool = scored.length ? scored : universe.map((e) => ({ e, s: 0 }));
  pool.sort((a, b) => b.s - a.s || (b.e.mcap ?? 0) - (a.e.mcap ?? 0));
  return pool.slice(0, limit).map((x) => ({ symbol: x.e.symbol, name: cleanName(x.e.name), via: "symbol" as const }));
}

/** Merge hit lists, keeping the first occurrence of each ticker. */
export function mergeHits(...lists: CompanyHit[][]): CompanyHit[] {
  const seen = new Set<string>();
  const out: CompanyHit[] = [];
  for (const l of lists) for (const h of l) if (!seen.has(h.symbol)) { seen.add(h.symbol); out.push(h); }
  return out;
}

/**
 * What Enter should do when no suggestion is highlighted.
 *  - an exact ticker match, or no suggestions: run the text as typed (so "BRK-B" or "RELIANCE IN" still work);
 *  - the top suggestion matched on NAME ("apple"): run that ticker;
 *  - otherwise (a ticker prefix like "aap"): run the text as typed, as it always did.
 */
export function enterTarget(text: string, hits: readonly CompanyHit[]): string {
  const t = text.trim();
  const top = hits[0];
  if (!top || /\s/.test(t) || hits.some((h) => h.symbol.toLowerCase() === t.toLowerCase())) return t;
  return top.via === "name" ? top.symbol : t;
}
