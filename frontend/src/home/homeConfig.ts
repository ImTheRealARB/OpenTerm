/**
 * What the HOME page shows (pure data + tiny helpers, unit-tested; no React, no DOM).
 *
 * HOME is a dense grid of "blocks". There are two kinds:
 *  - quote blocks: a short list of symbols with last price and % change (live: ticks repaint the numbers);
 *  - news blocks: the newest headlines of one /api/news section (source, age, title).
 * Symbols are Yahoo-style and spelled exactly as boards.ts (WEI / FX / CMDTY) spells them.
 */

export interface QuoteItem {
  symbol: string;
  label: string;
}

/** A row of a quote block: a small section heading (not selectable) or a symbol. */
export type QuoteRowDef = { head: string } | QuoteItem;

export interface QuoteBlock {
  kind: "quotes";
  id: string;
  title: string;
  rows: QuoteRowDef[];
}

/** The /api/news `section` values. "top" means no section (the mixed top headlines). */
export const NEWS_SECTIONS = ["markets", "economy", "companies", "commodities", "crypto", "tech", "india", "world"] as const;
export type NewsSection = (typeof NEWS_SECTIONS)[number];

export interface NewsBlock {
  kind: "news";
  id: string;
  title: string;
  /** One request per entry; two entries (commodities + crypto) are merged newest first. `undefined` = the plain top headlines. */
  sections: (NewsSection | undefined)[];
  limit: number;
}

export type HomeBlock = QuoteBlock | NewsBlock;

const q = (symbol: string, label: string): QuoteItem => ({ symbol, label });

export const BLOCKS: readonly HomeBlock[] = [
  {
    kind: "quotes", id: "indices", title: "INDICES",
    rows: [
      { head: "US" }, q("^GSPC", "S&P 500"), q("^IXIC", "NASDAQ"), q("^DJI", "DOW"),
      { head: "INDIA" }, q("^NSEI", "NIFTY 50"), q("^NSEBANK", "BANK NIFTY"), q("^BSESN", "SENSEX"),
      { head: "EUROPE" }, q("^FTSE", "FTSE 100"), q("^GDAXI", "DAX"), q("^FCHI", "CAC 40"),
      { head: "ASIA" }, q("^N225", "NIKKEI"), q("^HSI", "HANG SENG"), q("000001.SS", "SHANGHAI"),
    ],
  },
  {
    kind: "quotes", id: "assets", title: "FX · COMMODITIES · CRYPTO",
    rows: [
      { head: "FX" }, q("USDINR=X", "USD/INR"), q("EURUSD=X", "EUR/USD"), q("USDJPY=X", "USD/JPY"), q("DX-Y.NYB", "DOLLAR INDEX"),
      { head: "COMMODITIES" }, q("GC=F", "GOLD"), q("CL=F", "WTI"), q("BZ=F", "BRENT"), q("NG=F", "NAT GAS"), q("HG=F", "COPPER"),
      { head: "CRYPTO" }, q("BTC-USD", "BITCOIN"), q("ETH-USD", "ETHER"),
    ],
  },
  {
    kind: "quotes", id: "rates", title: "RATES · VOLATILITY",
    rows: [q("^TNX", "US 10Y YIELD"), q("^FVX", "US 5Y YIELD"), q("^IRX", "US 13W BILL"), q("^VIX", "VIX")],
  },
  { kind: "news", id: "top", title: "TOP HEADLINES", sections: [undefined], limit: 8 },
  { kind: "news", id: "markets", title: "MARKETS", sections: ["markets"], limit: 6 },
  { kind: "news", id: "economy", title: "ECONOMY", sections: ["economy"], limit: 6 },
  { kind: "news", id: "companies", title: "COMPANIES", sections: ["companies"], limit: 6 },
  { kind: "news", id: "tech", title: "TECH", sections: ["tech"], limit: 6 },
  { kind: "news", id: "india", title: "INDIA", sections: ["india"], limit: 6 },
  { kind: "news", id: "cc", title: "COMMODITIES · CRYPTO", sections: ["commodities", "crypto"], limit: 6 },
];

/** The quote block symbols, in order, without repeats. */
export function blockSymbols(blocks: readonly HomeBlock[] = BLOCKS): string[] {
  const out: string[] = [];
  for (const b of blocks) if (b.kind === "quotes") for (const r of b.rows) if ("symbol" in r && !out.includes(r.symbol)) out.push(r.symbol);
  return out;
}

/** Every symbol HOME needs one snapshot request and one subscription for: the tape's plus the blocks' (deduplicated). */
export function homeSymbols(tapeSymbols: readonly string[], blocks: readonly HomeBlock[] = BLOCKS): string[] {
  return [...new Set([...tapeSymbols, ...blockSymbols(blocks)])];
}

/** Short tape labels for the symbols people usually keep there; anything else is shown cleaned up (see `tapeLabel`). */
const TAPE_NAMES: Readonly<Record<string, string>> = {
  "^GSPC": "SPX", "^IXIC": "COMP", "^DJI": "DJI", "^NDX": "NDX", "^RUT": "RUT", "^FTSE": "FTSE", "^GDAXI": "DAX", "^FCHI": "CAC",
  "^N225": "N225", "^HSI": "HSI", "^NSEI": "NIFTY", "^NSEBANK": "BANKNIFTY", "^BSESN": "SENSEX", "^VIX": "VIX", "^TNX": "US10Y",
  "^FVX": "US5Y", "^IRX": "US13W", "GC=F": "GOLD", "SI=F": "SILVER", "BZ=F": "BRENT", "CL=F": "WTI", "NG=F": "NATGAS", "HG=F": "COPPER",
  "DX-Y.NYB": "DXY", "000001.SS": "SSE",
};

/** "USDINR=X" -> "USD/INR", "BTC-USD" -> "BTC", "RELIANCE.NS" -> "RELIANCE", "^FOO" -> "FOO". Known names win. */
export function tapeLabel(symbol: string): string {
  const known = TAPE_NAMES[symbol];
  if (known) return known;
  if (/^[A-Z]{6}=X$/.test(symbol)) return `${symbol.slice(0, 3)}/${symbol.slice(3, 6)}`;
  if (/^[A-Z]+-USD$/.test(symbol)) return symbol.slice(0, -4);
  return symbol.replace(/^\^/, "").replace(/=F$/, "").replace(/\.(NS|BO)$/, "");
}

/** Merges the newest-first lists of several news sections into one newest-first list of at most `limit` (no repeated ids). */
export function mergeNews<T extends { id: string; published: number | null }>(lists: readonly (readonly T[])[], limit: number): T[] {
  const seen = new Set<string>();
  const all: T[] = [];
  for (const l of lists) for (const i of l) if (!seen.has(i.id)) (seen.add(i.id), all.push(i));
  return all.sort((a, b) => (b.published ?? 0) - (a.published ?? 0)).slice(0, limit);
}

/** The /api/news query for one section ("top" = none). */
export function newsQuery(section: NewsSection | undefined, limit: number): { section?: string; limit: string } {
  return section ? { section, limit: String(limit) } : { limit: String(limit) };
}
