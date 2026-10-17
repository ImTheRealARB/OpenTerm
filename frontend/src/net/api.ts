/**
 * Data client. Same-key requests share one fetch; responses are cached briefly so panels and
 * prefetch reuse them. Every payload keeps the backend's source/as_of/stale envelope intact.
 */
import { gauges } from "../perf/metrics";

export interface Envelope<T> {
  data: T;
  source: string | null;
  as_of: number;
  age_s: number;
  stale: boolean;
  fallback_from: string[];
}

export interface Quote {
  symbol: string;
  name: string | null;
  currency: string | null;
  exchange: string | null;
  tz: string | null;
  price: number | null;
  prev_close: number | null;
  change: number | null;
  change_pct: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
  volume: number | null;
  high_52w: number | null;
  low_52w: number | null;
  market_time: number | null;
  source: string;
  as_of: number;
}

export interface Bars {
  symbol: string;
  range: string;
  interval: string;
  currency: string | null;
  exchange: string | null;
  tz: string | null;
  t: number[];
  o: (number | null)[];
  h: (number | null)[];
  l: (number | null)[];
  c: (number | null)[];
  v: (number | null)[];
  source: string;
  as_of: number;
}

export interface SearchHit {
  symbol: string;
  name: string | null;
  exchange: string | null;
  type: string | null;
  source: string;
}

export type QuoteResult = Envelope<Quote> | { error: string; kind: string; symbol: string };

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public kind = "unavailable",
    /** Each provider's reason, e.g. "gdelt: rate_limited (429 from upstream)". */
    public detail?: string,
  ) {
    super(message);
  }
}

const MAX_ENTRIES = 500;
const cache = new Map<string, { value: unknown; at: number }>();
const inflight = new Map<string, Promise<unknown>>();

async function request<T>(path: string, maxAgeMs: number): Promise<T> {
  const hit = cache.get(path);
  if (hit && performance.now() - hit.at < maxAgeMs) return hit.value as T;
  const pending = inflight.get(path);
  if (pending) return pending as Promise<T>;

  const t0 = performance.now();
  const p = (async () => {
    let res: Response;
    try {
      res = await fetch(path);
    } catch {
      throw new ApiError(0, "BACKEND DOWN");
    }
    const body = await res.json().catch(() => null);
    gauges.set(`api.${path.split("?")[0]}`, performance.now() - t0);
    if (!res.ok) throw new ApiError(res.status, body?.error ?? `HTTP ${res.status}`, body?.kind, body?.detail);
    cache.delete(path);
    cache.set(path, { value: body, at: performance.now() });
    if (cache.size > MAX_ENTRIES) cache.delete(cache.keys().next().value!);
    return body as T;
  })();
  inflight.set(path, p);
  try {
    return await p;
  } finally {
    inflight.delete(path);
  }
}

/** Uncached write (or read that must be fresh). Errors carry the backend's message. */
async function send<T>(method: string, path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      method,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "BACKEND DOWN");
  }
  const json = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, json?.error ?? `HTTP ${res.status}`, json?.kind, json?.detail);
  return json as T;
}

const qs = (o: Record<string, string | undefined>) =>
  new URLSearchParams(Object.entries(o).filter((e): e is [string, string] => !!e[1])).toString();

export const api = {
  quotes: (symbols: string[]) =>
    request<{ results: Record<string, QuoteResult> }>(`/api/quote?${qs({ symbols: symbols.join(",") })}`, 2000),
  history: (symbol: string, range?: string, interval?: string) =>
    request<Envelope<Bars>>(`/api/history?${qs({ symbol, range, interval })}`, 60_000),
  search: (q: string) => request<Envelope<SearchHit[]>>(`/api/search?${qs({ q })}`, 600_000),
  profile: (symbol: string) => request<Envelope<unknown>>(`/api/profile?${qs({ symbol })}`, 600_000),
  sources: () => request<SourcesPayload>("/api/sources", 1000),
  log: (after: number) => request<{ records: LogRecord[] }>(`/api/log?after=${after}`, 0),
  layouts: () => send<{ layouts: LayoutInfo[] }>("GET", "/api/layouts"),
  layout: (name: string) => send<{ name: string; state: unknown; updated_at: number }>("GET", `/api/layouts/${encodeURIComponent(name)}`),
  saveLayout: (name: string, state: unknown) =>
    send<{ name: string; updated_at: number }>("PUT", `/api/layouts/${encodeURIComponent(name)}`, { state }),
  deleteLayout: (name: string) => send<{ deleted: string }>("DELETE", `/api/layouts/${encodeURIComponent(name)}`),
  // `fresh` (F5) skips this client's short cache; the backend still serves its SWR envelope.
  news: (q: { symbol?: string; q?: string }, fresh = false) =>
    request<Envelope<NewsPayload>>(`/api/news?${qs(q)}`, fresh ? 0 : 30_000),
  movers: (fresh = false) => request<Envelope<MoversPayload>>("/api/movers", fresh ? 0 : 30_000),
  crypto: (vs: string, fresh = false) =>
    request<Envelope<{ vs: string; coins: Coin[] }>>(`/api/crypto?${qs({ vs })}`, fresh ? 0 : 15_000),
  watchlists: () => send<{ watchlists: WatchlistInfo[] }>("GET", "/api/watchlists"),
  watchlist: (name: string) => send<Watchlist>("GET", `/api/watchlists/${encodeURIComponent(name)}`),
  putWatchlist: (name: string, symbols: string[]) => send<Watchlist>("PUT", `/api/watchlists/${encodeURIComponent(name)}`, { symbols }),
  editWatchlist: (name: string, change: { add?: string[]; remove?: string[] }) =>
    send<Watchlist>("PATCH", `/api/watchlists/${encodeURIComponent(name)}`, change),
  deleteWatchlist: (name: string) => send<{ deleted: string }>("DELETE", `/api/watchlists/${encodeURIComponent(name)}`),
  cmdHistory: () => send<{ items: string[] }>("GET", "/api/cmdhistory"),
  pushCmdHistory: (cmds: string[]) => send<{ added: number }>("POST", "/api/cmdhistory", { cmds }),
};

export interface WatchlistInfo {
  name: string;
  count: number;
  updated_at: number;
}

export interface Watchlist {
  name: string;
  symbols: string[];
  updated_at: number;
}

export interface NewsItem {
  id: string;
  title: string;
  url: string;
  publisher: string | null;
  /** Epoch seconds. */
  published: number | null;
  summary: string | null;
  source: string;
}

export interface NewsPayload {
  kind: "top" | "symbol" | "keyword";
  query: string | null;
  items: NewsItem[];
  /** Feeds that did not answer this time (top stories only). */
  failed: string[];
}

export interface Mover {
  symbol: string;
  name: string | null;
  price: number | null;
  change: number | null;
  change_pct: number | null;
  volume: number | null;
}

export interface MoversPayload {
  tables: Record<string, Mover[]>;
  table_as_of: Record<string, string | null>;
  as_of_text: string | null;
  market_time: number | null;
  source: string;
}

export interface Coin {
  symbol: string;
  name: string | null;
  rank: number | null;
  quote: string;
  price: number | null;
  change_pct_1h: number | null;
  change_pct_24h: number | null;
  change_pct_7d: number | null;
  high_24h: number | null;
  low_24h: number | null;
  volume_24h: number | null;
  market_cap: number | null;
  updated: number | null;
  source: string;
}

export interface LayoutInfo {
  name: string;
  panels: number;
  updated_at: number;
}

/** Warm the most likely next call for a highlighted security: its quote and 1Y daily bars. */
export function prefetch(symbol: string): void {
  void api.quotes([symbol]).catch(() => {});
  void api.history(symbol, "1Y").catch(() => {});
}

export interface ProviderSummary {
  name: string;
  label: string;
  source: string;
  capabilities: string[];
  markets: string;
  terms: string;
  status: "OK" | "DEGRADED" | "DOWN" | "IDLE";
  down_for_s: number;
  latency_p50_ms: number | null;
  latency_p95_ms: number | null;
  calls: number;
  errors: number;
  last_error: string | null;
  last_error_age_s: number | null;
  last_ok_age_s: number | null;
  tokens_remaining: number;
  rate_per_s: number;
}

export interface SourcesPayload {
  providers: ProviderSummary[];
  keyed: { name: string; status: string; note: string }[];
  order: Record<string, string[]>;
  cache: { fresh_hits: number; stale_hits: number; misses: number; hit_pct: number | null; inflight: number; mem_entries: number };
  fixtures: boolean;
}

export interface LogRecord {
  seq: number;
  t: number;
  level: string;
  logger: string;
  msg: string;
}

// --- Phase 6: SEC fundamentals / filings / insiders, Yahoo holders ---
import type { FaPayload, FaPeriod, FilingsPayload, HoldersPayload, InsidersPayload } from "../functions/secTables";

/** `fresh` (F5) skips this client's short cache; the backend still serves its SWR envelope. */
export const secApi = {
  fa: (symbol: string, period: FaPeriod, fresh = false) =>
    request<Envelope<FaPayload>>(`/api/fa?${qs({ symbol, period })}`, fresh ? 0 : 300_000),
  filings: (symbol: string, form: string, fresh = false) =>
    request<Envelope<FilingsPayload>>(`/api/filings?${qs({ symbol, form })}`, fresh ? 0 : 60_000),
  insiders: (symbol: string, fresh = false) =>
    request<Envelope<InsidersPayload>>(`/api/insiders?${qs({ symbol })}`, fresh ? 0 : 120_000),
  holders: (symbol: string, fresh = false) =>
    request<Envelope<HoldersPayload>>(`/api/holders?${qs({ symbol })}`, fresh ? 0 : 300_000),
};
