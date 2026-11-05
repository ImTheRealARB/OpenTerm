/**
 * Company-name search for the GUI (pure: no React, no network, so vitest can test it).
 *
 * The data is the screener universe: one row per US stock, `[symbol, name, mcap]` is all we need here.
 * (`mcap` = market capitalisation = share price x number of shares; we use it only to put big companies first.)
 * Typing "apple" should suggest "AAPL  Apple Inc."; typing "aap" should too (symbol prefix).
 */

/** The columns of a screener row this file reads. */
export interface UniverseEntry {
  symbol: string;
  name: string;
  mcap: number | null;
  /** Shares traded today. Optional (old callers and tests omit it); plain-English commands use it to pick the most traded share class. */
  volume?: number | null;
}

/**
 * False for things that are not "the company's shares": preferred shares ("BAC^B"), warrants, rights, notes and SPAC units.
 * Name search for plain English skips them, otherwise "bank of america" would offer BAC^B first. A company's own ticker is
 * never affected, only name matching.
 */
export function isCompanyShare(e: UniverseEntry): boolean {
  if (e.symbol.includes("^")) return false; // screener spelling of a preferred series
  if (/\b(?:warrants?|rights?|preferred|notes?|debentures?)\b/i.test(e.name)) return false;
  // "...Acquisition Corp. Units" are SPAC bundles; "AllianceBernstein Holding L.P. Units" is a real company, so L.P. is let through.
  if (/\bunits?\b/i.test(e.name) && !/\bL\.?P\.?(?:\s|$)|limited partner/i.test(e.name)) return false;
  return true;
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

/** Edit distance where swapping two neighbouring letters costs 1 ("mircosoft" -> "microsoft" = 1). */
export function editDistance(a: string, b: string, max: number): number {
  if (Math.abs(a.length - b.length) > max) return max + 1;
  const prev2: number[] = [];
  let prev: number[] = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i++) {
    const cur = [i];
    let rowMin = i;
    for (let j = 1; j <= b.length; j++) {
      let v = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
      if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) v = Math.min(v, (prev2[j - 2] ?? 99) + 1);
      cur[j] = v;
      if (v < rowMin) rowMin = v;
    }
    if (rowMin > max) return max + 1; // already too far apart: stop early
    prev2.length = 0;
    prev2.push(...prev);
    prev = cur;
  }
  return prev[b.length];
}

/** Per universe: the spellings a company can be typed as (its first word, its first two words joined). Built once. */
const spellings = new WeakMap<readonly UniverseEntry[], { form: string; e: UniverseEntry }[]>();
function spellingsOf(universe: readonly UniverseEntry[]) {
  let list = spellings.get(universe);
  if (!list) {
    list = [];
    for (const e of universe) {
      if (!isCompanyShare(e)) continue;
      const w = norm(e.name.replace(/[’']/g, "")).split(" ");
      list.push({ form: w[0], e });
      if (w.length > 1) list.push({ form: w[0] + w[1], e });
    }
    spellings.set(universe, list);
  }
  return list;
}

/**
 * "Did you mean...": companies whose ticker or name looks most like `query` (shared two-letter pieces), used when a typed
 * symbol has no data. If nothing looks alike, falls back to the biggest companies so the user always has a next step.
 *
 * `opts.strict` is the plain-English mode: only companies whose first word (or first two words joined) is one or two letters
 * away from the typed word ("mircosoft" -> Microsoft), one entry per company, and NOTHING when no name is that close, so a
 * gibberish word never gets a suggestion.
 */
export function closestCompanies(query: string, universe: readonly UniverseEntry[], limit = 3, opts?: { strict?: boolean }): CompanyHit[] {
  if (opts?.strict) return closestStrict(query, universe, limit);
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

/** The strict "did you mean" of closestCompanies: small spelling mistakes only. */
function closestStrict(query: string, universe: readonly UniverseEntry[], limit: number): CompanyHit[] {
  const q = norm(query).replace(/ /g, "");
  if (q.length < 4) return [];
  const max = q.length >= 6 ? 2 : 1; // longer words can carry more typos
  const best = new Map<string, { e: UniverseEntry; d: number }>();
  for (const { form, e } of spellingsOf(universe)) {
    if (form === q) continue; // an exact spelling is a normal match, not a typo (and the caller already tried it)
    if (form[0] !== q[0] && !(form[0] === q[1] && form[1] === q[0])) continue; // a typo rarely changes the first letter
    const d = editDistance(q, form, max);
    if (d > max) continue;
    const key = norm(e.name).replace(/ (?:class [a-z0-9]|common|ordinary|capital|american depositary).*$/, ""); // share classes of one company count once
    const old = best.get(key);
    const better = !old || d < old.d || (d === old.d && (e.volume ?? 0) > (old.e.volume ?? 0));
    if (better) best.set(key, { e, d });
  }
  const out = [...best.values()].sort((a, b) => a.d - b.d || (b.e.mcap ?? 0) - (a.e.mcap ?? 0));
  return out.slice(0, limit).map((x) => ({ symbol: x.e.symbol, name: cleanName(x.e.name), via: "name" as const }));
}
