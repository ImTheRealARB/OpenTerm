/**
 * Plain-English screener (pure, unit-tested): "tech stocks with price under 50 and volume over 1 million"
 * -> EQS command args `SECTOR=TECH PRICE<50 VOL>1M` (the grammar of eqsFilter.ts, so it runs as `EQS <args>`).
 *
 * The screener universe only has these columns: price, change, %change, volume, market cap, country, IPO year, sector,
 * industry. Ratios that are not in it (P/E, dividend yield, beta, EPS ...) are NOT guessed: they are returned in
 * `unavailable` and shown as such. Any word that is not understood is returned in `unknown`, never silently dropped.
 * Terms are ANDed; several values of the same text field ("tech and healthcare") are ORed (SECTOR=TECH,HEALTH).
 */

export interface Interpreted {
  /** EQS args, one term per entry, e.g. ["SECTOR=TECH", "MCAP>10B"]. */
  args: string[];
  /** Human line parts: "SECTOR = TECHNOLOGY", "MKT CAP > 10B". */
  summary: string[];
  /** Words (uppercase) that were not understood. */
  unknown: string[];
  /** Ratios the screener data does not have (uppercase labels, e.g. "P/E"). */
  unavailable: string[];
}

type NumField = "MCAP" | "PRICE" | "PCT" | "VOL";
const FIELD_LABEL: Record<NumField, string> = { MCAP: "MKT CAP", PRICE: "PRICE", PCT: "%CHG", VOL: "VOLUME" };

/** Columns that exist, for messages. */
export const SCREENER_COLUMNS = "PRICE, %CHG, VOLUME, MKT CAP, COUNTRY, SECTOR, INDUSTRY";

const FIELD_WORDS: { f: NumField | `X:${string}`; words: string[] }[] = [
  { f: "X:P/E", words: ["price to earnings ratio", "price to earnings", "price earnings", "price/earnings", "p/e ratio", "pe ratio", "p/e", "pe"] },
  { f: "X:DIV YIELD", words: ["dividend yield", "div yield", "dividends", "dividend", "yield", "payout"] },
  { f: "X:BETA", words: ["beta", "volatility"] },
  { f: "X:EPS", words: ["eps", "earnings per share", "earnings"] },
  { f: "X:REVENUE", words: ["revenue", "revenues", "sales"] },
  { f: "X:MARGIN", words: ["profit margin", "margin", "margins", "profit", "profits"] },
  { f: "X:GROWTH", words: ["growth"] },
  { f: "X:DEBT", words: ["debt"] },
  { f: "X:ROE", words: ["roe", "return on equity"] },
  { f: "MCAP", words: ["market capitalization", "market capitalisation", "market cap", "market value", "marketcap", "mcap"] },
  { f: "VOL", words: ["trading volume", "shares traded", "volume", "traded"] },
  { f: "PCT", words: ["percent change", "pct change", "% change", "daily change", "change", "performance", "moved", "move"] },
  { f: "PRICE", words: ["share price", "stock price", "price", "priced", "trading at"] },
];

const OPS: { op: ">" | ">=" | "<" | "<=" | "="; words: string[] }[] = [
  { op: ">=", words: ["greater than or equal to", "at least", "no less than", "minimum of", ">="] },
  { op: "<=", words: ["less than or equal to", "at most", "no more than", "maximum of", "up to", "<="] },
  { op: "<", words: ["less than", "lower than", "smaller than", "fewer than", "cheaper than", "under", "below", "beneath", "<"] },
  { op: ">", words: ["greater than", "more than", "higher than", "bigger than", "larger than", "exceeding", "exceeds", "over", "above", ">"] },
  { op: "=", words: ["equal to", "equals", "exactly", "="] },
];

interface TextEntry { field: "SECTOR" | "INDUSTRY" | "COUNTRY"; value: string; label: string; words: string[] }
const TEXT_WORDS: TextEntry[] = [
  { field: "SECTOR", value: "TECH", label: "TECHNOLOGY", words: ["technology", "tech"] },
  { field: "INDUSTRY", value: "BIOTECH", label: "BIOTECHNOLOGY", words: ["biotechnology", "biotech"] },
  { field: "INDUSTRY", value: "PHARMA", label: "PHARMACEUTICALS", words: ["pharmaceuticals", "pharmaceutical", "pharma", "drug makers"] },
  { field: "SECTOR", value: "HEALTH", label: "HEALTH CARE", words: ["health care", "healthcare", "health", "medical"] },
  { field: "INDUSTRY", value: "BANK", label: "BANKS", words: ["banks", "banking", "bank"] },
  { field: "INDUSTRY", value: "INSURANCE", label: "INSURANCE", words: ["insurance", "insurers"] },
  { field: "SECTOR", value: "FINANCE", label: "FINANCE", words: ["financials", "financial", "finance"] },
  { field: "INDUSTRY", value: "OIL", label: "OIL", words: ["oil"] },
  { field: "SECTOR", value: "ENERGY", label: "ENERGY", words: ["energy"] },
  { field: "SECTOR", value: "UTILITIES", label: "UTILITIES", words: ["utilities", "utility"] },
  { field: "SECTOR", value: "STAPLES", label: "CONSUMER STAPLES", words: ["consumer staples", "staples"] },
  { field: "SECTOR", value: "DISCRETIONARY", label: "CONSUMER DISCRETIONARY", words: ["consumer discretionary", "discretionary"] },
  { field: "SECTOR", value: "CONSUMER", label: "CONSUMER", words: ["consumer"] },
  { field: "INDUSTRY", value: "RETAIL", label: "RETAIL", words: ["retailers", "retail"] },
  { field: "SECTOR", value: "INDUSTRIALS", label: "INDUSTRIALS", words: ["industrials", "industrial"] },
  { field: "SECTOR", value: "REAL", label: "REAL ESTATE", words: ["real estate", "reits", "reit"] },
  { field: "SECTOR", value: "TELECOM", label: "TELECOMMUNICATIONS", words: ["telecommunications", "telecom", "communications", "communication"] },
  { field: "SECTOR", value: "BASIC", label: "BASIC MATERIALS", words: ["basic materials", "materials", "mining"] },
  { field: "INDUSTRY", value: "SOFTWARE", label: "SOFTWARE", words: ["software"] },
  { field: "INDUSTRY", value: "SEMICONDUCTOR", label: "SEMICONDUCTORS", words: ["semiconductors", "semiconductor", "semis", "chips", "chipmakers"] },
  { field: "INDUSTRY", value: "AUTO", label: "AUTOMOTIVE", words: ["automotive", "autos", "auto", "carmakers"] },
  { field: "INDUSTRY", value: "AIR", label: "AIRLINES", words: ["airlines", "airline"] },
  { field: "COUNTRY", value: "US", label: "UNITED STATES", words: ["american", "usa", "u.s", "us"] },
  { field: "COUNTRY", value: "CN", label: "CHINA", words: ["chinese", "china"] },
  { field: "COUNTRY", value: "IN", label: "INDIA", words: ["indian", "india"] },
  { field: "COUNTRY", value: "JP", label: "JAPAN", words: ["japanese", "japan"] },
  { field: "COUNTRY", value: "IL", label: "ISRAEL", words: ["israeli", "israel"] },
  { field: "COUNTRY", value: "CA", label: "CANADA", words: ["canadian", "canada"] },
  { field: "COUNTRY", value: "UK", label: "UNITED KINGDOM", words: ["british", "uk"] },
  { field: "COUNTRY", value: "DE", label: "GERMANY", words: ["german", "germany"] },
  { field: "COUNTRY", value: "BR", label: "BRAZIL", words: ["brazilian", "brazil"] },
];

const FILLER = new Set([
  "stocks", "stock", "companies", "company", "shares", "share", "equities", "equity", "names", "firms", "with", "that", "have", "has", "had",
  "a", "an", "the", "and", "or", "show", "me", "find", "list", "get", "give", "whose", "which", "who", "are", "is", "was", "were", "of", "in", "for", "only",
  "ratio", "value", "level", "all", "any", "to", "than", "per", "from", "today", "now", "currently", "i", "want", "looking", "screen", "screener",
  "biggest", "largest", "&", "their", "its", "it", "on", "at", "by", "be", "being",
]);

const UNIT: Record<string, number> = { k: 1e3, thousand: 1e3, m: 1e6, mm: 1e6, million: 1e6, b: 1e9, bn: 1e9, billion: 1e9, t: 1e12, tn: 1e12, trillion: 1e12 };
const NUM = /^\$?(\d+(?:\.\d+)?|\.\d+)(k|mm|m|bn|b|tn|t)?(%?)$/;

const CAP_SIZES: Record<string, string[]> = {
  mega: ["MCAP>200B"],
  large: ["MCAP>10B"],
  big: ["MCAP>10B"],
  mid: ["MCAP>2B", "MCAP<10B"],
  medium: ["MCAP>2B", "MCAP<10B"],
  small: ["MCAP<2B"],
  micro: ["MCAP<300M"],
  tiny: ["MCAP<300M"],
};
const CAP_LABEL: Record<string, string> = { mega: "MKT CAP > 200B", large: "MKT CAP > 10B", big: "MKT CAP > 10B", mid: "MKT CAP 2B-10B", medium: "MKT CAP 2B-10B", small: "MKT CAP < 2B", micro: "MKT CAP < 300M", tiny: "MKT CAP < 300M" };

/** "10000000000" -> "10B", 1500000 -> "1.5M", 50 -> "50". */
export function fmtNum(n: number): string {
  const abs = Math.abs(n);
  for (const [s, m] of [["T", 1e12], ["B", 1e9], ["M", 1e6], ["K", 1e3]] as const) {
    if (abs >= m) {
      const v = Math.round((n / m) * 1e6) / 1e6;
      return `${v}${s}`;
    }
  }
  return String(Math.round(n * 1e6) / 1e6);
}

function tokenize(text: string): string[] {
  const t = text
    .toLowerCase()
    .replace(/(\d),(?=\d{3}\b)/g, "$1")
    .replace(/-(cap|caps)\b/g, " $1")
    .replace(/(>=|<=|>|<|=)/g, " $1 ")
    .replace(/[;!?()"']/g, " ")
    .replace(/,/g, " ")
    .replace(/(\w)\.(\s|$)/g, "$1 ")
    .replace(/\bu\.s\.?/g, "us");
  return t.split(/\s+/).filter(Boolean);
}

/** Longest phrase from `table` starting at i. */
function phrase<T extends { words: string[] }>(tokens: string[], i: number, table: T[]): { entry: T; len: number; word: string } | null {
  let best: { entry: T; len: number; word: string } | null = null;
  for (const entry of table)
    for (const w of entry.words) {
      const parts = w.split(" ");
      if (parts.length > tokens.length - i) continue;
      if (parts.every((p, k) => tokens[i + k] === p) && (!best || parts.length > best.len)) best = { entry, len: parts.length, word: w };
    }
  return best;
}

interface Num { value: number; pct: boolean; dollar: boolean; mult: number; len: number }

function readNumber(tokens: string[], i: number): Num | null {
  const m = NUM.exec(tokens[i] ?? "");
  if (!m) return null;
  let value = Number(m[1]);
  let mult = 1;
  let len = 1;
  if (m[2]) mult = UNIT[m[2]];
  else if (tokens[i + 1] && /^(thousand|million|billion|trillion)$/.test(tokens[i + 1])) {
    mult = UNIT[tokens[i + 1]];
    len = 2;
  }
  value *= mult;
  return { value, pct: m[3] === "%", dollar: tokens[i].startsWith("$"), mult, len };
}

const OP_FLIP = { ">": "<", ">=": "<=", "<": ">", "<=": ">=", "=": "=" } as const;

export function interpretScreener(text: string): Interpreted {
  const tokens = tokenize(text);
  const out: Interpreted = { args: [], summary: [], unknown: [], unavailable: [] };
  const textVals: Record<string, { values: string[]; labels: string[] }> = {};
  const numClauses: string[] = [];
  const numSummary: string[] = [];
  let pending: NumField | `X:${string}` | null = null;
  let dir: 1 | -1 = 1;
  let last: NumField | null = null;
  let sort: string | null = null;
  const unavail = (l: string) => {
    if (!out.unavailable.includes(l)) out.unavailable.push(l);
  };
  const unk = (w: string) => out.unknown.push(w.toUpperCase());

  const emit = (field: NumField | `X:${string}`, op: keyof typeof OP_FLIP, n: Num, value = n.value) => {
    if (field.startsWith("X:")) return unavail(field.slice(2));
    const f = field as NumField;
    let o = op;
    let v = value;
    if (f === "PCT" && dir === -1) {
      o = OP_FLIP[op];
      v = -v;
    }
    numClauses.push(`${f}${o}${fmtNum(v)}`);
    numSummary.push(`${FIELD_LABEL[f]} ${o} ${f === "PRICE" ? "$" : ""}${fmtNum(v)}${f === "PCT" ? "%" : ""}`);
    last = f;
  };

  /** Field for a number with no field word before it. */
  const infer = (n: Num, i: number): NumField | `X:${string}` | null => {
    const ahead = phrase(tokens, i + n.len, FIELD_WORDS);
    if (ahead) {
      return ahead.entry.f;
    }
    if (pending) return pending;
    if (n.pct) return "PCT";
    if (n.mult >= 1e9) return "MCAP";
    if (n.dollar && n.mult === 1) return "PRICE";
    if (last) return last;
    if (n.mult > 1) return "MCAP";
    return null;
  };

  for (let i = 0; i < tokens.length; ) {
    const w = tokens[i];

    // sorted by <field> [ascending|descending]
    if ((w === "sorted" || w === "sort" || w === "order" || w === "ordered" || w === "ranked" || w === "rank") && tokens[i + 1] === "by") {
      const f = phrase(tokens, i + 2, FIELD_WORDS);
      const asc = /^(asc|ascending|lowest)$/.test(tokens[i + 2 + (f?.len ?? 0)] ?? "");
      const sym = tokens[i + 2] === "symbol" || tokens[i + 2] === "ticker" ? "SYMBOL" : tokens[i + 2] === "name" ? "NAME" : null;
      if (f && !String(f.entry.f).startsWith("X:")) {
        sort = `SORT=${asc ? "+" : ""}${f.entry.f}`;
        i += 2 + f.len + (asc || /^(desc|descending|highest)$/.test(tokens[i + 2 + f.len] ?? "") ? 1 : 0);
        continue;
      }
      if (sym) {
        sort = `SORT=${sym}`;
        i += 3;
        continue;
      }
      if (f) {
        unavail(String(f.entry.f).slice(2));
        i += 2 + f.len;
        continue;
      }
    }

    // gainers / losers
    if (w === "gainers" || w === "winners") {
      numClauses.push("PCT>0"); numSummary.push("%CHG > 0%"); i++; continue;
    }
    if (w === "losers") {
      numClauses.push("PCT<0"); numSummary.push("%CHG < 0%"); i++; continue;
    }
    if (w === "penny") {
      numClauses.push("PRICE<5"); numSummary.push("PRICE < $5"); i++; continue;
    }

    // up / down
    if (!(w === "up" && tokens[i + 1] === "to") && /^(up|gaining|gained|rising|rose|risen|climbed)$/.test(w)) { pending = "PCT"; dir = 1; i++; continue; }
    if (/^(down|falling|fell|dropped|dropping|losing|lost|declined|declining)$/.test(w)) { pending = "PCT"; dir = -1; i++; continue; }

    // large cap, small cap ...
    if (CAP_SIZES[w] && /^(cap|caps|capitalization|capitalisation)$/.test(tokens[i + 1] ?? "")) {
      numClauses.push(...CAP_SIZES[w]);
      numSummary.push(CAP_LABEL[w]);
      last = "MCAP";
      i += 2;
      continue;
    }

    // between X and Y
    if (w === "between" || w === "from") {
      const a = readNumber(tokens, i + 1);
      const sep = a ? tokens[i + 1 + a.len] : undefined;
      const b = a && (sep === "and" || sep === "to" || sep === "-") ? readNumber(tokens, i + 2 + a.len) : null;
      if (a && b) {
        const field = infer(b, i + 2 + a.len) ?? infer(a, i + 1);
        const bRaw = Number(NUM.exec(tokens[i + 2 + a.len])![1]);
        // unit carried from the second number: "between 2 and 10 billion" -> 2B and 10B
        const lo = a.mult > 1 ? a.value : a.value * (b.mult > 1 ? b.mult : 1);
        void bRaw;
        if (field) {
          emit(field, ">=", a, lo);
          emit(field, "<=", b);
        } else unk(`between ${tokens[i + 1]} and ${tokens[i + 2 + a.len]}`);
        const ahead = phrase(tokens, i + 2 + a.len + b.len, FIELD_WORDS);
        i += 2 + a.len + b.len + (ahead && ahead.entry.f === field ? ahead.len : 0);
        pending = null;
        dir = 1;
        continue;
      }
    }

    // field word
    const fp = phrase(tokens, i, FIELD_WORDS);
    if (fp) {
      pending = fp.entry.f;
      if (fp.entry.f === "PCT" && dir !== -1) dir = 1;
      i += fp.len;
      // "change" alone after up/down stays signed; a plain field resets direction
      if (fp.entry.f !== "PCT") dir = 1;
      continue;
    }

    // comparator + number
    const op = phrase(tokens, i, OPS);
    if (op) {
      const n = readNumber(tokens, i + op.len);
      if (n) {
        let o: keyof typeof OP_FLIP = op.entry.op;
        let after = i + op.len + n.len;
        // "50 or more" / "50 and above" are handled by the next branch (suffix comparators), here the direct form
        const field = infer(n, i + op.len);
        const ahead = phrase(tokens, after, FIELD_WORDS);
        if (ahead && ahead.entry.f === field) after += ahead.len;
        if (field) emit(field, o, n);
        else unk(`${op.word} ${tokens[i + op.len]}`);
        void o;
        pending = null;
        dir = 1;
        i = after;
        continue;
      }
    }

    // bare number after a field word ("price 50", "up 5%") or "50 or more"
    const bn = readNumber(tokens, i);
    if (bn) {
      const tail = tokens.slice(i + bn.len, i + bn.len + 2).join(" ");
      const suffix = /^(or more|and above|and over|or higher|\+)/.test(tail) ? ">=" : /^(or less|and below|and under|or lower|or fewer)/.test(tail) ? "<=" : null;
      const field = infer(bn, i);
      if (field) {
        const o: keyof typeof OP_FLIP = suffix ?? (pending === "PCT" ? ">=" : "=");
        emit(field, o, bn);
        let after = i + bn.len + (suffix ? (tokens[i + bn.len] === "+" ? 1 : 2) : 0);
        const ahead = phrase(tokens, after, FIELD_WORDS);
        if (ahead && ahead.entry.f === field) after += ahead.len;
        pending = null;
        dir = 1;
        i = after;
        continue;
      }
      unk(tokens[i]);
      i++;
      continue;
    }

    // sector / industry / country
    const tp = phrase(tokens, i, TEXT_WORDS);
    if (tp) {
      const e = tp.entry;
      const slot = (textVals[e.field] ??= { values: [], labels: [] });
      if (!slot.values.includes(e.value)) {
        slot.values.push(e.value);
        slot.labels.push(e.label);
      }
      i += tp.len;
      continue;
    }

    if (FILLER.has(w) || OPS.some((o) => o.words.includes(w)) || w === "between" || w === "not") {
      i++;
      continue;
    }
    unk(w);
    i++;
  }

  // A trailing "up" / "down" with no number: gainers / losers.
  if (pending === "PCT" && !numClauses.some((c) => c.startsWith("PCT"))) {
    numClauses.push(dir === 1 ? "PCT>0" : "PCT<0");
    numSummary.push(dir === 1 ? "%CHG > 0%" : "%CHG < 0%");
  }

  for (const field of ["SECTOR", "INDUSTRY", "COUNTRY"] as const) {
    const s = textVals[field];
    if (!s) continue;
    out.args.push(`${field}=${s.values.join(",")}`);
    out.summary.push(`${field} = ${s.labels.join(" OR ")}`);
  }
  out.args.push(...numClauses);
  out.summary.push(...numSummary);
  if (sort) out.args.push(sort);
  return out;
}

/** True when the text reads like English rather than EQS terms (`SECTOR=TECH MCAP>10B`). */
export function looksLikeEnglish(text: string): boolean {
  const t = text.trim();
  if (!t) return false;
  if (/[<>=]/.test(t)) return false;
  const words = t.toLowerCase().split(/\s+/);
  if (words.length >= 3) return true;
  return words.some((w) => FILLER.has(w) && w !== "and") || words.some((w) => OPS.some((o) => o.words.includes(w)));
}

/** The message under the filter line when something was left out (uppercase). Null when everything was understood. */
export function interpretNotes(r: Interpreted): string[] {
  const notes: string[] = [];
  if (r.unknown.length) notes.push(`DID NOT UNDERSTAND: ${r.unknown.join(" ")}`);
  if (r.unavailable.length) notes.push(`NOT IN SCREENER DATA (IGNORED): ${r.unavailable.join(", ")}. COLUMNS: ${SCREENER_COLUMNS}`);
  return notes;
}
