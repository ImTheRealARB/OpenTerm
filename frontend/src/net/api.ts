/**
 * Data client. Same-key requests share one fetch; responses are cached briefly so panels and
 * prefetch reuse them. Every payload keeps the backend's source/as_of/stale envelope intact.
 */
import { gauges } from "../perf/metrics";
import type { JobRec } from "./jobFrames";
import { keyRequired, type KeyRequiredInfo } from "./keyRequired";

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
    /** Phase 11: the missing key's env name on a 424 KEY REQUIRED envelope (see keyRequired.ts). */
    public key?: string,
    /** Phase 12: 0-based column of a BT rule syntax error. */
    public col?: number,
  ) {
    super(message);
  }
}

/** The key and message of a KEY REQUIRED failure, or null for any other error. */
export function keyRequiredOf(e: ApiError | null | undefined): KeyRequiredInfo | null {
  return e ? keyRequired(e.status, { key: e.key, detail: e.detail }) : null;
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
    if (!res.ok) throw new ApiError(res.status, body?.error ?? `HTTP ${res.status}`, body?.kind, body?.detail, body?.key);
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
  if (!res.ok) throw new ApiError(res.status, json?.error ?? `HTTP ${res.status}`, json?.kind, json?.detail, json?.key, json?.col);
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
  // Phase 11 API keys: uncached (`send`); the backend never returns a value, only status.
  keys: () => send<KeysPayload>("GET", "/api/keys"),
  putKey: (name: string, fields: Record<string, string>) => send<KeyRow>("PUT", `/api/keys/${encodeURIComponent(name)}`, { fields }),
  testKey: (name: string) => send<KeyRow>("POST", `/api/keys/${encodeURIComponent(name)}/test`),
  deleteKey: (name: string) => send<KeyRow>("DELETE", `/api/keys/${encodeURIComponent(name)}`),
  putLlmCap: (cap: number) => send<KeysPayload["spend"]>("PUT", "/api/llm/cap", { cap }),
  // Phase 11 job runner (uncached). `job` carries the result; the list does not.
  jobs: () => send<{ jobs: JobRec[] }>("GET", "/api/jobs"),
  job: (id: string) => send<JobRec>("GET", `/api/jobs/${encodeURIComponent(id)}`),
  submitJob: (kind: string, params: unknown) => send<JobRec>("POST", "/api/jobs", { kind, params }),
  cancelJob: (id: string) => send<JobRec>("DELETE", `/api/jobs/${encodeURIComponent(id)}`),
  clearFinishedJobs: () => send<{ cleared: number }>("DELETE", "/api/jobs?state=finished"),
};

export type KeyState = "MISSING" | "UNTESTED" | "OK" | "INVALID" | "QUOTA" | "ERROR";

export interface KeyRow {
  name: string;
  present: boolean;
  source: "env" | "keyring" | "dotenv" | null;
  state: KeyState;
  /** Epoch seconds of the last test. */
  checked_at: number | null;
  detail: string | null;
  /** Env names to fill in, e.g. ["ALPACA_KEY_ID", "ALPACA_SECRET_KEY"]. */
  fields: string[];
  purpose: string;
  phase: number;
  signup: string;
}

export interface KeysPayload {
  keys: KeyRow[];
  spend: { today: number; cap: number };
}

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

// --- Phase 7: macro (FRED, MACRO, RATES, ERN, ECO) ---
export interface FredSeries {
  id: string;
  title: string | null;
  units: string | null;
  frequency: string | null;
  seasonal_adjustment: string | null;
  last_updated: string | null;
  /** fred_api | curated (built-in metadata for well-known ids) | none (keyless CSV: values only). */
  meta_source: string;
  /** Observation dates, epoch seconds (UTC midnight). */
  t: number[];
  /** Values; null = missing observation. */
  v: (number | null)[];
  last_value: number;
  last_date: string;
  prev_value: number | null;
  change: number | null;
  missing: number;
  source: string;
  as_of: number;
  range: string;
  key_set: boolean;
}

export interface MacroRow {
  id: string;
  label?: string;
  title: string | null;
  units: string | null;
  frequency: string | null;
  seasonal_adjustment?: string | null;
  last_value?: number;
  last_date?: string;
  prev_value?: number | null;
  change?: number | null;
  source?: string;
  age_s?: number;
  stale?: boolean;
  error?: string;
  /** Search mode only. */
  observation_end?: string | null;
  popularity?: number | null;
}

export interface MacroPayload {
  mode: "curated" | "search";
  query: string | null;
  /** "FRED_API_KEY" when search across all of FRED is unavailable without a key. */
  needs_key: string | null;
  rows: MacroRow[];
}

export interface CurveCompare {
  date: string;
  yields: (number | null)[];
  spread_2s10s: number | null;
}

export interface YieldCurve {
  date: string;
  tenors: string[];
  years: number[];
  yields: (number | null)[];
  spread_2s10s: number | null;
  compare: Record<string, CurveCompare>;
  note: string | null;
  source: string;
  as_of: number;
}

export interface Earning {
  symbol: string;
  name: string | null;
  time: "PRE" | "POST" | null;
  fiscal_quarter: string | null;
  eps_forecast: number | null;
  n_ests: number | null;
  last_year_eps: number | null;
  last_year_date: string | null;
  eps: number | null;
  surprise_pct: number | null;
  market_cap: number | null;
}

export interface EarningsPayload {
  date: string;
  as_of_text: string | null;
  rows: Earning[];
  source: string;
  as_of: number;
}

export interface EcoEvent {
  date: string;
  /** HH:MM US Eastern; null when the agency gives only a date. */
  time: string | null;
  ts: number;
  name: string;
  agency: string;
  major: boolean;
  source: string;
}

export interface EcoPayload {
  start: string;
  days: number;
  events: EcoEvent[];
  /** Agencies whose feed did not answer. */
  failed: string[];
  /** Last date the source feeds cover. */
  coverage_end: string | null;
  key_set: boolean;
}

export const macroApi = {
  fred: (id: string, range: string, fresh = false) =>
    request<Envelope<FredSeries>>(`/api/fred?${qs({ id, range })}`, fresh ? 0 : 60_000),
  macro: (q: string, fresh = false) => request<Envelope<MacroPayload>>(`/api/macro?${qs({ q })}`, fresh ? 0 : 60_000),
  rates: (fresh = false) => request<Envelope<YieldCurve>>("/api/rates", fresh ? 0 : 60_000),
  earnings: (date: string, fresh = false) =>
    request<Envelope<EarningsPayload>>(`/api/earnings?${qs({ date })}`, fresh ? 0 : 30_000),
  eco: (start: string | null, days: number, fresh = false) =>
    request<Envelope<EcoPayload>>(`/api/eco?${qs({ start: start ?? undefined, days: String(days) })}`, fresh ? 0 : 60_000),
};

// --- Phase 8: portfolios and alerts ---
export interface Position {
  symbol: string;
  qty: number;
  cost: number | null;
  currency: string | null;
  notes: string | null;
}

export interface PortfolioInfo {
  name: string;
  base: string;
  count: number;
  updated_at: number;
}

export interface Portfolio {
  name: string;
  base: string;
  positions: Position[];
  updated_at: number;
}

export type PositionIn = Partial<Position> & { symbol: string; qty: number };

export interface Alert {
  id: number;
  symbol: string;
  op: ">" | "<";
  unit: "price" | "pct";
  value: number;
  status: "active" | "triggered";
  created_at: number;
  triggered_at: number | null;
  trigger_price: number | null;
}

const pf = (name: string) => `/api/portfolios/${encodeURIComponent(name)}`;

export const api8 = {
  portfolios: () => send<{ portfolios: PortfolioInfo[] }>("GET", "/api/portfolios"),
  portfolio: (name: string) => send<Portfolio>("GET", pf(name)),
  putPortfolio: (name: string, positions: PositionIn[], base?: string) =>
    send<Portfolio>("PUT", pf(name), base ? { positions, base } : { positions }),
  editPortfolio: (name: string, change: { add?: PositionIn[]; set?: PositionIn[]; remove?: string[]; base?: string }) =>
    send<Portfolio>("PATCH", pf(name), change),
  deletePortfolio: (name: string) => send<{ deleted: string }>("DELETE", pf(name)),
  alerts: () => send<{ alerts: Alert[] }>("GET", "/api/alerts"),
  createAlert: (a: { symbol: string; op: ">" | "<"; unit: "price" | "pct"; value: number }) => send<Alert>("POST", "/api/alerts", a),
  deleteAlert: (id: number) => send<{ deleted: number }>("DELETE", `/api/alerts/${id}`),
  triggerAlert: (id: number, price: number, at: number) =>
    send<{ alert: Alert; changed: boolean }>("POST", `/api/alerts/${id}/trigger`, { price, at }),
  rearmAlert: (id: number) => send<Alert>("POST", `/api/alerts/${id}/rearm`),
  clearAlerts: () => send<{ deleted: number }>("DELETE", "/api/alerts?status=triggered"),
};

// --- Phase 9: screener (EQS), peers (COMP) ---
export interface ScreenerPayload {
  columns: string[];
  /** [symbol, name, last, chg, pct, volume, mcap, country_i, ipo, sector_i, industry_i] (see functions/eqsFilter.ts). */
  rows: [string, string, number | null, number | null, number | null, number | null, number | null, number, number | null, number, number][];
  sectors: string[];
  industries: string[];
  countries: string[];
  count: number;
  as_of_text: string | null;
  market: string;
  source: string;
  as_of: number;
}

export interface PeerInfo {
  symbol: string;
  name: string | null;
  market_cap: number | null;
  sector: string | null;
  industry: string | null;
  score?: number | null;
}

export interface PeersPayload {
  symbol: string;
  /** "yahoo" = Yahoo recommended symbols; "industry" = same industry in the Nasdaq screener (US only). */
  basis: "yahoo" | "industry";
  self: PeerInfo;
  peers: PeerInfo[];
}

/** Daily+ Yahoo bars carry dividend/split-adjusted closes (`adj`); other sources leave it out. */
export type BarsAdj = Bars & { adj?: (number | null)[] | null };

export const api9 = {
  history: (symbol: string, range: string, interval?: string, fresh = false) =>
    request<Envelope<BarsAdj>>(`/api/history?${qs({ symbol, range, interval })}`, fresh ? 0 : 60_000),
  /** About 1 MB, cached server-side for 15 min; the client keeps it 5 min. */
  screener: (fresh = false) => request<Envelope<ScreenerPayload>>("/api/screener", fresh ? 0 : 300_000),
  peers: (symbol: string) => request<Envelope<PeersPayload>>(`/api/peers?${qs({ symbol })}`, 600_000),
};

// --- Phase 10: settings ---
export interface SettingsDoc {
  version: number;
  /** null until the first save. */
  settings: Record<string, unknown> | null;
  updated_at: number | null;
}

export const settingsApi = {
  get: () => send<SettingsDoc>("GET", "/api/settings"),
  put: (settings: unknown) => send<{ version: number; settings: unknown; updated_at: number }>("PUT", "/api/settings", { version: 1, settings }),
};

// --- Phase 12: backtester ---
export interface BtSource {
  symbol?: string;
  name?: string | null;
  as_of?: number | null;
  age_s?: number | null;
  stale?: boolean;
}
export interface BtLabels {
  headline: string;
  engine: string;
  prices: "ADJ" | "RAW";
  fees_bps: number;
  slip_bps: number;
  costs?: string;
  warmup_bars: number;
  short?: boolean;
  sources: BtSource[];
  benchmark?: string;
  data_note?: string;
}
export interface BtTrade {
  symbol: string;
  direction: number;
  entry_time: string;
  exit_time: string;
  entry_price: number | null;
  exit_price: number | null;
  size: number | null;
  pnl: number | null;
  pnl_pct?: number | null;
  commission: number | null;
  holding_bars?: number | null;
  exit_reason: string;
}
export interface BtRunCard {
  id: string;
  rule: string | null;
  strategy: string | null;
  symbols: string[];
  interval: string;
  range: string;
  engine?: string;
  labels: BtLabels;
  created_at: number;
  metrics: Record<string, number | null>;
}
export interface BtRunFull extends BtRunCard {
  /** [epoch seconds, value] */
  equity: [number, number][];
  benchmark: [number, number][];
  trades: BtTrade[];
  code?: string | null;
}
export interface BtRunRequest {
  rule?: string;
  code?: string;
  strategy?: string;
  symbols: string[];
  interval: string;
  range: string;
  options: { short?: boolean; fees_bps?: number; slip_bps?: number; cash?: number; bench?: string; engine?: string };
  /** Phase 14: MKT=options (an OSA structure instead of a rule). */
  structure?: Record<string, unknown>;
}

/** Result of a bt.mc job: Vibe's trade-order permutation test plus the bootstrap Sharpe interval. */
export interface BtMcResult {
  run_id: string;
  actual_sharpe: number;
  actual_max_dd: number;
  p_value_sharpe: number;
  p_value_max_dd: number;
  simulated_sharpe_mean: number;
  simulated_sharpe_std: number;
  simulated_sharpe_p5: number;
  simulated_sharpe_p95: number;
  n_simulations: number;
  n_trades: number;
  sharpe_samples: number[];
  bootstrap: { observed_sharpe?: number; ci_lower?: number; ci_upper?: number; median_sharpe?: number; prob_positive?: number;
    confidence?: number; n_bootstrap?: number; error?: string };
  labels: BtLabels & { validation?: string };
}
export interface BtWfWindow {
  window: number;
  start: string;
  end: string;
  return: number;
  sharpe: number;
  max_dd: number;
  trades: number;
  win_rate: number;
}
/** Result of a bt.wf job. */
export interface BtWfResult {
  run_id: string;
  n_windows: number;
  windows: BtWfWindow[];
  profitable_windows: number;
  consistency_rate: number;
  return_mean: number;
  return_std: number;
  sharpe_mean: number;
  sharpe_std: number;
  labels: BtLabels & { validation?: string };
}

export interface BtCompare {
  a: BtRunFull;
  b: BtRunFull;
  /** B minus A, for every metric both runs have. */
  diff: Record<string, number>;
}

export interface BtImported {
  symbol: string;
  rows: number;
  first_date: string;
  last_date: string;
  created_at: number;
  label: string;
}

export interface BtStrategyCard {
  name: string;
  kind: "python" | "rule";
  updated_at: number;
}
export interface BtStrategy extends BtStrategyCard {
  code: string;
}

export const btApi = {
  strategies: () => send<{ strategies: BtStrategyCard[] }>("GET", "/api/bt/strategies"),
  strategy: (name: string) => send<BtStrategy>("GET", `/api/bt/strategies/${encodeURIComponent(name)}`),
  /** Python code, or a rule. The server checks both (the sandbox allowlist for code) and says why it refuses. */
  putStrategy: (name: string, body: { code: string } | { rule: string }) =>
    send<BtStrategyCard>("PUT", `/api/bt/strategies/${encodeURIComponent(name)}`, body),
  deleteStrategy: (name: string) => send<{ deleted: string }>("DELETE", `/api/bt/strategies/${encodeURIComponent(name)}`),
  imports: () => send<{ symbols: BtImported[] }>("GET", "/api/bt/import"),
  deleteImport: (symbol: string) => send<{ deleted: string }>("DELETE", `/api/bt/import/${encodeURIComponent(symbol)}`),
  /** Stores the CSV text as the symbol's daily bars (replaces an earlier import). */
  importBars: async (symbol: string, csv: string): Promise<BtImported & { volume: boolean }> => {
    let res: Response;
    try {
      res = await fetch(`/api/bt/import?symbol=${encodeURIComponent(symbol)}`, { method: "POST", headers: { "Content-Type": "text/plain" }, body: csv });
    } catch {
      throw new ApiError(0, "BACKEND DOWN");
    }
    const json = await res.json().catch(() => null);
    if (!res.ok) throw new ApiError(res.status, json?.error ?? `HTTP ${res.status}`, json?.kind, json?.detail);
    return json;
  },
  runs: () => send<{ runs: BtRunCard[] }>("GET", "/api/bt/runs"),
  compare: (a: string, b: string) => send<BtCompare>("GET", `/api/bt/compare?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`),
  /** The server-built export: a CSV part (`trades`, `equity`, `metrics`) or the Pine Script of a rule run. */
  exportText: async (id: string, fmt: "csv" | "pine", part = "trades"): Promise<string> => {
    let res: Response;
    try {
      res = await fetch(`/api/bt/runs/${encodeURIComponent(id)}/export?fmt=${fmt}&part=${part}`);
    } catch {
      throw new ApiError(0, "BACKEND DOWN");
    }
    if (!res.ok) {
      const json = await res.json().catch(() => null);
      throw new ApiError(res.status, json?.error ?? `HTTP ${res.status}`, json?.kind, json?.detail);
    }
    return res.text();
  },
  /** Start a Monte Carlo (`mc`) or walk-forward (`wf`) job on a stored run. */
  validate: (id: string, kind: "mc" | "wf", body: Record<string, unknown> = {}) =>
    send<JobRec>("POST", `/api/bt/runs/${encodeURIComponent(id)}/${kind}`, body),
  /** The job, plus the id its run will be stored under (open it at once when the answer is cached). */
  run: (body: BtRunRequest) => send<JobRec & { run_id: string; run?: BtRunFull }>("POST", "/api/bt/run", body),
  get: (id: string) => send<BtRunFull>("GET", `/api/bt/runs/${encodeURIComponent(id)}`),
};

// --- Phase 13: research functions (EE, EEO, ANR, MGMT, ...) and valuation (DCF, WACC, RV) ---
import type { TablePayload } from "../research/tablePayload";

/** One call for every table function: `fn` is the backend route name (ee, anr, ipo, ...). `fresh` (F5) skips the client cache. */
export const researchApi = {
  get: (fn: string, params: Record<string, string | undefined>, fresh = false) =>
    request<Envelope<TablePayload>>(`/api/research/${fn}?${qs(params)}`, fresh ? 0 : 120_000),
  valuation: (fn: string, params: Record<string, string | undefined>, fresh = false) =>
    request<Envelope<TablePayload>>(`/api/valuation/${fn}?${qs(params)}`, fresh ? 0 : 30_000),
  /** Phase 14: options, rates, futures (OMON, OV, OSA, YAS, CT, COT, ...). */
  deriv: (fn: string, params: Record<string, string | undefined>, fresh = false) =>
    request<Envelope<TablePayload>>(`/api/deriv/${fn}?${qs(params)}`, fresh ? 0 : 60_000),
  /** Phase 14: non-US curves, credit spreads and auctions (RATES views). */
  rates: (fn: string, params: Record<string, string | undefined>, fresh = false) =>
    request<Envelope<TablePayload>>(`/api/rates/${fn}?${qs(params)}`, fresh ? 0 : 60_000),
};

/** Phase 15: quant jobs (RISK, PORT OPT, PORT ATTR, ...). The answer is the job; its `result` is an envelope of a table payload. */
export interface ValRow {
  date: string;
  value: number;
  flow: number;
}

export const quantApi = {
  run: (fn: string, body: Record<string, unknown>) => send<JobRec>("POST", `/api/quant/${encodeURIComponent(fn)}`, body),
  vals: (name: string) => send<{ rows: ValRow[] }>("GET", `${pf(name)}/vals`),
  putVals: (name: string, rows: ValRow[]) => send<{ rows: ValRow[] }>("PUT", `${pf(name)}/vals`, { rows }),
};

/** Phase 15: Kite Connect (read-only data source). Login is `/api/kite/login`, opened in a new tab; the api key never reaches this app. */
export interface KiteStatus {
  state: string;
  message?: string | null;
  user?: string | null;
  logged_in_at?: string | null;
  expires_note?: string | null;
}

export const kiteApi = {
  loginUrl: "/api/kite/login",
  status: () => send<KiteStatus>("GET", "/api/kite/status"),
  logout: () => send<KiteStatus>("POST", "/api/kite/logout"),
};

// Phase 13 step 6: news keyword alerts (ALRT NEWS WORD [SYM]); stored by the backend, evaluated here on each news refresh.
export interface NewsAlert {
  id: number;
  word: string;
  /** null = the market top stories. */
  symbol: string | null;
  status: "active" | "triggered";
  created_at: number;
  triggered_at: number | null;
  headline: string | null;
  url: string | null;
}

export const newsAlertsApi = {
  list: () => send<{ alerts: NewsAlert[] }>("GET", "/api/newsalerts"),
  create: (a: { word: string; symbol: string | null }) => send<NewsAlert>("POST", "/api/newsalerts", a),
  delete: (id: number) => send<{ deleted: number }>("DELETE", `/api/newsalerts/${id}`),
  trigger: (id: number, headline: string, url: string, at: number) =>
    send<{ alert: NewsAlert; changed: boolean }>("POST", `/api/newsalerts/${id}/trigger`, { headline, url, at }),
  rearm: (id: number) => send<NewsAlert>("POST", `/api/newsalerts/${id}/rearm`),
  clear: () => send<{ deleted: number }>("DELETE", "/api/newsalerts?status=triggered"),
};
