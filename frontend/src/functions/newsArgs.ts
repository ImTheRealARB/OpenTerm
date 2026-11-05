import type { SecurityRef } from "../command/markets";

/** The filters of a "pool" query: headlines pooled from the curated feed table. Every field is optional; all given ones must match. */
export interface NewsFilters {
  region?: string; // country / area code: IN, US, CN, UK, EU, JP, WORLD
  sector?: string; // tech, banks, energy, pharma, autos ...
  commodity?: string; // oil, gold, copper, gas, wheat ...
  section?: string; // markets, economy, companies, commodities, crypto, tech, india, world, all
  q?: string; // free text, every word must appear
}

export type NewsQuery =
  | { kind: "top" }
  | { kind: "symbol"; symbol: string }
  | { kind: "keyword"; q: string }
  | ({ kind: "pool" } & NewsFilters)
  | { kind: "error"; message: string };

/**
 * Section words you can type bare: `NEWS TECH`, `NEWS INDIA`. Must equal `SECTIONS` in backend providers/news_feeds.py
 * (plus ALL = every feed). Values of the other filters (region, sector, commodity) are checked by the server, which
 * answers with the list of legal values, so they are not duplicated here.
 */
export const NEWS_SECTIONS = ["MARKETS", "ECONOMY", "COMPANIES", "COMMODITIES", "CRYPTO", "TECH", "INDIA", "WORLD", "ALL"];

// Words that introduce a filter and the field they fill. SEARCH takes the rest of the line.
const WORD_FIELD: Record<string, keyof NewsFilters> = {
  COUNTRY: "region",
  REGION: "region",
  SECTOR: "sector",
  COMMODITY: "commodity",
  SECTION: "section",
};

export const NEWS_USAGE =
  "N [TOP | TECH | INDIA | MARKETS | ECONOMY | COMPANIES | COMMODITIES | CRYPTO | WORLD] [COUNTRY IN] [SECTOR BANKS] [COMMODITY GOLD] [SEARCH words]";

/**
 * `N` (market top stories), `AAPL N` (that security; also the panel's sticky security), `N words...`
 * (GDELT keyword search), `N TOP` (top stories even when the panel has a security), and the feed filters:
 * `N TECH`, `N INDIA`, `N COUNTRY IN`, `N SECTOR BANKS`, `N COMMODITY GOLD`, `N SEARCH rate cut`, combinable
 * (`N TECH COUNTRY IN SEARCH chip`).
 */
export function newsQuery(args: string[], security?: SecurityRef): NewsQuery {
  const words = args.map((a) => a.trim()).filter(Boolean);
  if (words.length === 1 && words[0].toUpperCase() === "TOP") return { kind: "top" };

  const first = words[0]?.toUpperCase();
  if (first && (NEWS_SECTIONS.includes(first) || first in WORD_FIELD || first === "SEARCH")) return parseFilters(words);

  if (words.length) return { kind: "keyword", q: words.join(" ").toUpperCase() };
  if (security) return { kind: "symbol", symbol: security.symbol };
  return { kind: "top" };
}

function parseFilters(words: string[]): NewsQuery {
  const f: NewsFilters = {};
  for (let i = 0; i < words.length; i++) {
    const w = words[i].toUpperCase();
    if (w === "SEARCH") {
      // Everything after SEARCH is the text, so `SEARCH rate cut` needs no quotes.
      const text = words.slice(i + 1).join(" ");
      if (text.length < 2) return { kind: "error", message: "SEARCH NEEDS 2+ CHARACTERS, E.G. N SEARCH RATE CUT" };
      f.q = text;
      break;
    }
    const field = WORD_FIELD[w];
    if (field) {
      const value = words[i + 1];
      if (!value) return { kind: "error", message: `${w} NEEDS A VALUE, E.G. N ${w} ${field === "region" ? "IN" : field === "sector" ? "BANKS" : "GOLD"}` };
      f[field] = value.toUpperCase();
      i++;
    } else if (NEWS_SECTIONS.includes(w)) {
      f.section = w;
    } else {
      return { kind: "error", message: `${w} IS NOT A NEWS FILTER. ${NEWS_USAGE}` };
    }
  }
  // Text alone searches every feed (the fast pooled search); GDELT keyword search is the bare `N words` form.
  if (!f.section && !f.region && !f.sector && !f.commodity) f.section = "ALL";
  return { kind: "pool", ...f };
}

/** Query-string params for `GET /api/news` (the server lower-cases / upper-cases them as needed). */
export function newsParams(q: NewsQuery): { symbol?: string; q?: string; region?: string; sector?: string; commodity?: string; section?: string } {
  switch (q.kind) {
    case "symbol":
      return { symbol: q.symbol };
    case "keyword":
      return { q: q.q };
    case "pool": {
      const { kind: _kind, ...filters } = q;
      return filters;
    }
    default:
      return {};
  }
}

/** The visible "what am I looking at" line under the title, e.g. `SECTION TECH · COUNTRY IN · SEARCH "rate cut"`. Empty for unfiltered views. */
export function newsFilterLine(q: NewsQuery): string {
  if (q.kind !== "pool") return "";
  const parts: string[] = [];
  if (q.section) parts.push(`SECTION ${q.section.toUpperCase()}`);
  if (q.region) parts.push(`COUNTRY ${q.region.toUpperCase()}`);
  if (q.sector) parts.push(`SECTOR ${q.sector.toUpperCase()}`);
  if (q.commodity) parts.push(`COMMODITY ${q.commodity.toUpperCase()}`);
  if (q.q) parts.push(`SEARCH "${q.q}"`);
  return parts.join(" · ");
}

/** The panel title for a query. */
export function newsTitle(q: NewsQuery): string {
  switch (q.kind) {
    case "symbol":
      return `NEWS: ${q.symbol}`;
    case "keyword":
      return `NEWS SEARCH: ${q.q}`;
    case "pool":
      return "NEWS FEEDS";
    default:
      return "TOP NEWS";
  }
}

/**
 * What to try when a query came back with no headlines (shown under "NO HEADLINES").
 * Pure on purpose, so it is unit-tested without a browser.
 */
export function newsEmptyHint(q: NewsQuery): string {
  switch (q.kind) {
    case "symbol":
      return `No headlines for ${q.symbol}. Try N <words> for a keyword search, N TOP for market stories, or F5 to retry.`;
    case "keyword":
      return `Nothing matched ${q.q}. Try fewer or broader words, N TOP for market stories, or F5 to retry.`;
    case "pool":
      return `Nothing in the feeds matched ${newsFilterLine(q)}. Drop one filter, try N SEARCH <fewer words>, or F5 to retry.`;
    default:
      return "No stories came back. Press F5 to retry; sources that are not answering are named in the header.";
  }
}
