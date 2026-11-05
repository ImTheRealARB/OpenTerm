/**
 * Turns a few words ("bank of america", "reliance", "gold", "eur usd") into a ticker. Pure: no React, no window, no network.
 *
 * SPEED. v1 re-normalised all ~7,000 company names for every word run it tried (7-28 ms a phrase). Here the company list is
 * indexed ONCE per list (a WeakMap keyed by the array, so a new list rebuilds and the old one is garbage collected):
 *   - every name is normalised once ("McDonald's Corporation" -> "mcdonalds corporation");
 *   - words -> companies map, plus the same words in sorted order so "all words starting with micr" is a binary search.
 * A word run then looks at the few companies that contain its first word instead of scanning everything.
 *
 * ORDER for one word run (first hit wins): alias table (nlAliases: indices, commodities, crypto, nicknames, Indian names)
 *   -> currency pair -> exact ticker -> company name.
 *
 * COMPANY NAME RULES
 *   - Preferred shares, warrants, rights, notes and SPAC units never match a name (companySearch.isCompanyShare).
 *   - A name matches when the run's words are whole words of the name, in order ("coca cola" in "Coca-Cola Company (The)").
 *     Only if nothing matches that way, the LAST word may be the start of a word ("micros" -> Microsoft), at least 4 letters.
 *     So "has" never opens Hasbro.
 *   - Tiers: 3 = the run IS the company's core name ("apple" = Apple Inc., "coca cola" = Coca-Cola Company), 2 = the name starts
 *     with it, 1 = it appears later in the name. Only the best tier is kept.
 *   - Share classes of one company are ONE company; the most traded class wins (screener volume, then market cap): Alphabet ->
 *     GOOGL, Berkshire -> BRK-B. Different companies: the biggest wins only if it is DOMINANCE (10) times bigger than the next,
 *     else the user gets choices (max 5). We never guess between companies.
 *   - Screener spells share classes `BRK/B`; the command grammar needs the Yahoo spelling `BRK-B` (toYahoo).
 */
import { cleanName, isCompanyShare, type UniverseEntry } from "../gui/companySearch";
import { fxPair, lookupAlias } from "./nlAliases";
import { COMMON_WORDS, FILLER } from "./nlWords";

/** Filler unless the user typed it in CAPITALS ("HAS", "NOW" are tickers there). */
export const isFiller = (w: string, upper: ReadonlySet<string>): boolean => FILLER.has(w) && !upper.has(w);

/** The top company's market cap must be this many times the next company's to be picked without asking. */
export const DOMINANCE = 10;
export const MAX_CHOICES = 5;
/** A company found only by a partial name needs at least this market cap to count as certain when several names are in one phrase. */
const BIG_ENOUGH = 1e9;

export interface Pick {
  symbol: string;
  name: string;
}

export type Resolved =
  | { kind: "one"; symbol: string; name: string; /** Alias text for the "understood as" line, e.g. "Reliance Industries on NSE". */ label?: string; /** Safe to use next to other companies in one phrase. */ strong: boolean }
  | { kind: "many"; picks: Pick[] }
  | { kind: "no" };

/** Screener spelling -> Yahoo / command spelling: `BRK/B` -> `BRK-B`. */
export const toYahoo = (symbol: string): string => symbol.replace("/", "-");

// ---------------------------------------------------------------------------------------------------------------------
// The index
// ---------------------------------------------------------------------------------------------------------------------

interface Row {
  /** Yahoo-style symbol. */
  symbol: string;
  /** Short display name ("Apple Inc."). */
  name: string;
  /** Normalised name with a space on both ends, for whole-word searching. */
  hay: string;
  /** Normalised name without the legal tail: "apple inc common stock" -> "apple". */
  core: string;
  /** Same company = same group (share classes share one). */
  group: string;
  mcap: number;
  vol: number;
}

interface Index {
  byTicker: Map<string, Row>;
  byWord: Map<string, Row[]>;
  /** The keys of byWord, sorted: prefix lookups are a binary search. */
  words: string[];
}

/** Lower case, apostrophes dropped ("McDonald's" -> "mcdonalds"), any other punctuation becomes a space. */
const norm = (s: string): string => s.toLowerCase().replace(/[’']/g, "").replace(/[^a-z0-9]+/g, " ").replace(/\s+/g, " ").trim();

/** The share-class / security-type tail of a Nasdaq-style name: "... class a common stock", "... ordinary shares". */
const CLASS_TAIL = / (?:class [a-z0-9]\b.*|capital stock.*|common stock.*|common shares.*|ordinary shares?.*|american depositary.*|series .*)$/;
const LEGAL = new Set("inc incorporated corp corporation company co ltd limited plc llc lp com sa nv ag se".split(" "));

function coreOf(nameN: string): string {
  const words = nameN.replace(CLASS_TAIL, "").split(" ").filter((w) => w !== "the");
  while (words.length > 1 && LEGAL.has(words[words.length - 1])) words.pop();
  return words.join(" ");
}

const indexes = new WeakMap<readonly UniverseEntry[], Index>();

function indexOf(uni: readonly UniverseEntry[]): Index {
  let idx = indexes.get(uni);
  if (idx) return idx;
  const byTicker = new Map<string, Row>();
  const byWord = new Map<string, Row[]>();
  for (const e of uni) {
    if (!isCompanyShare(e)) continue;
    const nameN = norm(e.name);
    const symbol = toYahoo(e.symbol);
    const row: Row = {
      symbol,
      name: cleanName(e.name),
      hay: ` ${nameN} `,
      core: coreOf(nameN),
      group: nameN.replace(CLASS_TAIL, ""),
      mcap: e.mcap ?? 0,
      vol: e.volume ?? 0,
    };
    byTicker.set(symbol.toLowerCase(), row);
    byTicker.set(e.symbol.toLowerCase(), row);
    for (const w of new Set(nameN.split(" "))) {
      const list = byWord.get(w);
      if (list) list.push(row);
      else byWord.set(w, [row]);
    }
  }
  idx = { byTicker, byWord, words: [...byWord.keys()].sort() };
  indexes.set(uni, idx);
  return idx;
}

/** Companies having a word that starts with `pre` (binary search for the first such word, then walk). */
function startingWith(idx: Index, pre: string): Row[] {
  let lo = 0;
  let hi = idx.words.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (idx.words[mid] < pre) lo = mid + 1;
    else hi = mid;
  }
  const out = new Set<Row>();
  for (let i = lo; i < idx.words.length && idx.words[i].startsWith(pre); i++) for (const r of idx.byWord.get(idx.words[i])!) out.add(r);
  return [...out];
}

// ---------------------------------------------------------------------------------------------------------------------
// Resolving one word run
// ---------------------------------------------------------------------------------------------------------------------

/** Among rows of one company, the one people trade: most volume, then biggest market cap, then shortest ticker. */
const mostTraded = (rows: Row[]): Row =>
  rows.reduce((a, b) => (b.vol !== a.vol ? (b.vol > a.vol ? b : a) : b.mcap !== a.mcap ? (b.mcap > a.mcap ? b : a) : b.symbol.length < a.symbol.length ? b : a));

/** `auto` false = the match was partial or late in the name: show it as a choice, never run it silently. */
function pickCompany(hits: { r: Row; tier: number }[], auto: boolean): Resolved {
  const best = Math.max(...hits.map((h) => h.tier));
  const top = hits.filter((h) => h.tier === best).map((h) => h.r);
  const groups = new Map<string, Row[]>();
  for (const r of top) {
    const g = groups.get(r.group);
    if (g) g.push(r);
    else groups.set(r.group, [r]);
  }
  const ranked = [...groups.values()]
    .map((rows) => ({ rep: mostTraded(rows), cap: Math.max(...rows.map((r) => r.mcap)) }))
    .sort((a, b) => b.cap - a.cap);
  const [first, second] = ranked;
  const dominant = auto && (!second || (first.cap > 0 && first.cap >= DOMINANCE * second.cap));
  if (dominant) return { kind: "one", symbol: first.rep.symbol, name: first.rep.name, strong: best >= 3 || first.cap >= BIG_ENOUGH };
  return { kind: "many", picks: ranked.slice(0, MAX_CHOICES).map((x) => ({ symbol: x.rep.symbol, name: x.rep.name })) };
}

function byName(raw: string[], idx: Index): Resolved {
  const q0 = norm(raw.join(" ")); // "amazon.com" -> "amazon com", like the names in the index
  const words = q0.split(" ");
  if (!q0) return { kind: "no" };
  // An everyday word alone ("best", "buy") is not a company name.
  if (words.length === 1 && (q0.length < 3 || COMMON_WORDS.has(q0))) return { kind: "no" };
  // Pass 1: whole words (also "kohl" for "Kohl's": the possessive s was cut from what the user typed, so try the word + s).
  // Pass 2: the last word may be the start of a word ("micros"): shown as a choice only, never run silently.
  for (const pass of ["whole", "possessive", "partial"] as const) {
    const q = pass === "possessive" ? q0 + "s" : q0;
    const last = words[words.length - 1];
    if (pass === "partial" && last.length < 4) break; // "has" must not become Hasbro
    const first = pass === "possessive" && words.length === 1 ? q : words[0];
    const cand = pass === "partial" && words.length === 1 ? startingWith(idx, q) : (idx.byWord.get(first) ?? []);
    const needle = pass === "partial" ? ` ${q}` : ` ${q} `;
    const hits: { r: Row; tier: number }[] = [];
    for (const r of cand) {
      const at = r.hay.indexOf(needle);
      if (at >= 0) hits.push({ r, tier: r.core === q ? 3 : at === 0 ? 2 : 1 });
    }
    if (!hits.length) continue;
    // Late in the name ("general electric" inside "Portland General Electric") or partial: ask, do not guess.
    const best = Math.max(...hits.map((h) => h.tier));
    return pickCompany(hits, pass !== "partial" && best >= 2);
  }
  return { kind: "no" };
}

/**
 * One word run -> a company, a few candidates, or nothing. `idx` is null before the company list is loaded (then only the
 * alias table and currency pairs work). `upper`: words the user typed in CAPITALS, which may be tickers even when they are English words.
 */
function resolveRun(words: string[], idx: Index | null, upper: ReadonlySet<string>): Resolved {
  const run = words.join(" ");
  const alias = lookupAlias(run);
  if (alias) return { kind: "one", symbol: alias.symbol, name: alias.label, label: alias.label, strong: true };
  if (words.length <= 4) {
    const fx = fxPair(run);
    if (fx) return { kind: "one", symbol: fx.symbol, name: fx.label, label: fx.label, strong: true };
  }
  if (!idx) return { kind: "no" };
  if (words.length === 1) {
    const w = words[0];
    const t = !COMMON_WORDS.has(w) || upper.has(w) ? idx.byTicker.get(w) : undefined; // "has" is a word, "HAS" is Hasbro
    if (t) return { kind: "one", symbol: t.symbol, name: t.name, strong: true };
  }
  return byName(words, idx);
}

// ---------------------------------------------------------------------------------------------------------------------
// Finding companies inside a whole phrase
// ---------------------------------------------------------------------------------------------------------------------

export interface Found {
  res: Resolved;
  start: number;
  len: number;
}

const isNumber = (w: string): boolean => /^\d+$/.test(w);

/** A run never starts or ends on a filler word, and a lone number is not a company ("nifty 50" is fine: it ends on one). */
const validRun = (words: string[], start: number, len: number, upper: ReadonlySet<string>): boolean =>
  !isFiller(words[start], upper) && !isFiller(words[start + len - 1], upper) && !(len === 1 && isNumber(words[start]));

/** The best single company in the phrase: longest run first; at one length a clear answer beats a list; then leftmost. */
export function findCompany(words: string[], uni: readonly UniverseEntry[] | null, upper: ReadonlySet<string> = new Set()): Found | null {
  const idx = uni ? indexOf(uni) : null;
  for (let len = words.length; len >= 1; len--) {
    let many: Found | null = null;
    for (let start = 0; start + len <= words.length; start++) {
      if (!validRun(words, start, len, upper)) continue;
      const res = resolveRun(words.slice(start, start + len), idx, upper);
      if (res.kind === "one") return { res, start, len };
      if (res.kind === "many" && !many) many = { res, start, len };
    }
    if (many) return many;
  }
  return null;
}

/**
 * Several companies named without "vs" ("apple microsoft nvidia 1 year"). Only when EVERY word is part of a company (numbers and
 * filler aside) and each one is certain; otherwise null and the caller uses findCompany. A small unknown name next to a famous
 * one ("apple software") is therefore not turned into a compare.
 */
export function findCompanies(words: string[], uni: readonly UniverseEntry[] | null, upper: ReadonlySet<string> = new Set()): Found[] | null {
  const idx = uni ? indexOf(uni) : null;
  const out: Found[] = [];
  let i = 0;
  while (i < words.length) {
    if (isFiller(words[i], upper) || isNumber(words[i])) {
      i++;
      continue;
    }
    let got: Found | null = null;
    for (let len = words.length - i; len >= 1 && !got; len--) {
      if (!validRun(words, i, len, upper)) continue;
      const res = resolveRun(words.slice(i, i + len), idx, upper);
      if (res.kind !== "no") got = { res, start: i, len };
    }
    if (!got || got.res.kind !== "one" || !got.res.strong) return null;
    out.push(got);
    i += got.len;
  }
  const symbols = new Set(out.map((f) => (f.res.kind === "one" ? f.res.symbol : "")));
  return out.length >= 2 && symbols.size === out.length ? out : null;
}

/** Words of the phrase that no company run covers and that could be a mistyped name: not filler, not a number, 4+ letters. */
export function unresolvedWords(words: string[]): string[] {
  return words.filter((w) => !FILLER.has(w) && !COMMON_WORDS.has(w) && /^[a-z]{4,}$/.test(w));
}
