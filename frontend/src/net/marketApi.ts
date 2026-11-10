/** Market data client: quotes, price bars, search, news, movers, the crypto board, the US screener and peers. */
import { get, TTL } from "./core";
import type {
  BarsAdj, Coin, Envelope, MoversPayload, NewsPayload, PeersPayload, QuoteResult, ScreenerPayload, SearchHit,
} from "./types";

export const marketApi = {
  // `source` pins one data source (SRC=): the backend asks only that source and names it in an error.
  quotes: (symbols: string[], source?: string) =>
    get<{ results: Record<string, QuoteResult> }>("/api/quote", { symbols: symbols.join(","), source }, TTL.s2),
  history: (symbol: string, range?: string, interval?: string, fresh = false, source?: string) =>
    get<Envelope<BarsAdj>>("/api/history", { symbol, range, interval, source }, TTL.m1, fresh),
  /** How many days back each minute candle length reaches for this symbol right now (the deepest source that is on decides). */
  historyLimits: (symbol: string) =>
    get<{ symbol: string; intraday_days: Record<string, number>; source: string[] }>("/api/history/limits", { symbol }, TTL.s30),
  search: (q: string) => get<Envelope<SearchHit[]>>("/api/search", { q }, TTL.m10),
  profile: (symbol: string, source?: string) => get<Envelope<unknown>>("/api/profile", { symbol, source }, TTL.m10),
  // `fresh` (F5) skips this client's short cache; the backend still serves its SWR envelope.
  news: (q: { symbol?: string; q?: string; section?: string; limit?: string; region?: string; sector?: string; commodity?: string; source?: string }, fresh = false) =>
    get<Envelope<NewsPayload>>("/api/news", q, TTL.s30, fresh),
  movers: (fresh = false) => get<Envelope<MoversPayload>>("/api/movers", undefined, TTL.s30, fresh),
  crypto: (vs: string, fresh = false) => get<Envelope<{ vs: string; coins: Coin[] }>>("/api/crypto", { vs }, TTL.s15, fresh),
  /** About 1 MB, cached server-side for 15 min; the client keeps it 5 min. */
  screener: (fresh = false) => get<Envelope<ScreenerPayload>>("/api/screener", undefined, TTL.m5, fresh),
  peers: (symbol: string) => get<Envelope<PeersPayload>>("/api/peers", { symbol }, TTL.m10),
};

/** Warm the most likely next call for a highlighted security: its quote and 1Y daily bars. */
export function prefetch(symbol: string): void {
  // Both ignored on purpose: this only warms the cache; the panel's own request repeats the call and shows any failure.
  void marketApi.quotes([symbol]).catch(() => {});
  void marketApi.history(symbol, "1Y").catch(() => {});
}
