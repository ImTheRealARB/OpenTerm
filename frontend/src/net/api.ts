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
  /** Why a skipped source was skipped, when worth saying (e.g. kite: "KITE LOGIN EXPIRED: run KITE LOGIN"). */
  fallback_notes?: Record<string, string>;
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
export async function send<T>(method: string, path: string, body?: unknown): Promise<T> {
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
  /** How many days back each minute candle length reaches for this symbol right now (the deepest source that is on decides). */
  historyLimits: (symbol: string) =>
    request<{ symbol: string; intraday_days: Record<string, number>; source: string[] }>(`/api/history/limits?${qs({ symbol })}`, 30_000),
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

export interface PresetItem {
  id?: string;
  formula?: string;
  params: number[];
  label: string;
}

export interface IndicatorPreset {
  name: string;
  items: PresetItem[];
  updated_at: number;
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
  /** -1 to +1: the source's own score (Marketaux only), not ours. Null for every other source. */
  sentiment?: number | null;
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
  /** Phase 19: e.g. `FOMC: STALE ...` when the Fed page did not answer. */
  notes?: string[];
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

/** One starter strategy offered by BT EDIT <NEW NAME> (GET /api/bt/templates). */
export interface BtTemplate {
  id: string;
  title: string;
  summary: string;
  code: string;
}

/** The sandbox check answer: `ok`, or `ok: false` with the text ("LINE 3: IMPORT os IS NOT ALLOWED ...", or no LINE prefix). */
export type BtCheck = { ok: true } | { ok: false; error: string };

export const btApi = {
  templates: () => send<{ templates: BtTemplate[] }>("GET", "/api/bt/templates"),
  /** Runs the sandbox rules over the code without saving it (the editor's live check). */
  check: (code: string) => send<BtCheck>("POST", "/api/bt/check", { code }),
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

// --- Phase 19: GP drawings and event markers, world data ---
export interface ChartEvent {
  date: string;
  kind: "E" | "D" | "S";
  detail: string;
}
export interface ChartEvents {
  symbol: string;
  events: ChartEvent[];
  missing: string[];
  notes: string[];
  source: string;
}

/** GIP: bars built from the ticks the server has seen. `v` is null when no tick carried volume. */
export interface TickBars {
  symbol: string;
  bar_s: number;
  ticks: number;
  since_ms: number | null;
  last_ms: number | null;
  synthetic: boolean;
  sessions: number;
  source_code: string | null;
  t: number[];
  o: number[];
  h: number[];
  l: number[];
  c: number[];
  v: number[] | null;
}

/** SECF: one OpenFIGI listing (exchange code is OpenFIGI's own). */
export interface FigiListing {
  figi: string | null;
  composite_figi: string | null;
  share_class_figi: string | null;
  ticker: string | null;
  name: string | null;
  exch_code: string | null;
  security_type: string | null;
  market_sector: string | null;
  description: string | null;
}
export interface FigiItem {
  kind: "ISIN" | "CUSIP" | "SEDOL" | "FIGI";
  id: string;
  status: "FOUND" | "NOT FOUND" | "BAD CHECK DIGIT" | "ERROR";
  message: string | null;
  listings: FigiListing[];
}
export interface FigiResult {
  items: FigiItem[];
  note: string;
}

/** ECST: one indicator series (annual unless a DBnomics series says otherwise). */
export interface WorldSeries {
  country: string;
  country_name: string;
  indicator: string;
  label: string;
  unit: string;
  freq: string;
  t: number[];
  v: number[];
  periods: string[];
  last_period: string;
  last_value: number;
  updated: string | null;
  source: string;
  dataset?: string | null;
}
/**
 * DBSRCH (`/api/world/dbsearch`): DBnomics search. `mode` DATASETS lists datasets for the words; SERIES lists the matching series of one dataset.
 * `provider_name` names the ORIGINAL data provider (DBnomics only mirrors it). `ref` is the `DBN:` id ECST opens (null = ECST cannot take that id).
 * A null date or count means the API did not give one; the last period of a series is not in the list at all.
 */
export interface DbsDatasetRow {
  provider: string;
  provider_name: string;
  dataset: string;
  name: string;
  matching: number | null;
  series: number | null;
  updated: string | null;
  indexed: string | null;
}
export interface DbsSeriesRow {
  provider: string;
  dataset: string;
  series: string;
  name: string;
  freq: string;
  indexed: string | null;
  ref: string | null;
}
export interface DbsDatasets { mode: "DATASETS"; total: number; offset: number; items: DbsDatasetRow[]; note: string; source: string }
export interface DbsSeries { mode: "SERIES"; provider: string; dataset: string; dataset_name: string; total: number; offset: number; items: DbsSeriesRow[]; note: string; source: string }
export type DbsPayload = DbsDatasets | DbsSeries;
export interface WecoCell {
  v: number;
  year: number;
  stale: boolean;
}
export interface WecoRow {
  iso3: string;
  name: string;
  cells: Record<string, WecoCell | null>;
}
export interface WecoPayload {
  rows: WecoRow[];
  columns: { alias: string; label: string; unit: string }[];
  failed: string[];
  note: string;
  source: string;
}
export interface CenbRow {
  bank: string;
  name: string;
  last: string | null;
  next: string | null;
  after: string | null;
  days: number | null;
  rate: number | null;
  rate_as_of: string | null;
  rate_label: string | null;
  rate_note: string | null;
  dates: string[];
  url: string;
  note: string | null;
}
export interface CenbPayload {
  today: string;
  rows: CenbRow[];
  calendar_as_of: string;
  note: string;
  notes: string[];
}

/** NRG: one energy price row (FRED CSV). `error` set = this series did not answer. */
export interface NrgRow {
  id: string;
  alias: string;
  label: string;
  group: string;
  unit: string;
  freq: string;
  last: number | null;
  date: string | null;
  chg: number | null;
  pct: number | null;
  lo: number | null;
  hi: number | null;
  pos: number | null;
  n: number;
  stale: boolean;
  error: string | null;
}
export interface NrgPayload {
  rows: NrgRow[];
  spread: { value: number; date: string; label: string; unit: string } | null;
  failed: string[];
  groups: string[];
  note: string;
}
/** SHIP: one sea chokepoint (IMF PortWatch daily ship counts). Averages are over the days on record; None = not enough data, never a guess. */
export interface ShipRow {
  id: string;
  name: string;
  date: string;
  age_days: number;
  stale: boolean;
  last: number | null;
  avg7: number | null;
  base: number | null;
  chg_pct: number | null;
  tanker: number | null;
  container: number | null;
  dry_bulk: number | null;
  capacity: number | null;
  n_days: number;
  base_days: number;
  series: [string, number | null][];
}
export interface ShipPayload {
  rows: ShipRow[];
  newest: string;
  note: string;
}
/** PORTS: one port (IMF PortWatch daily port calls). Averages are over the days on record; None = not enough data, never a guess.
 *  imp7 / exp7 are PortWatch's own modelled daily trade estimates, averaged over the same 7 days. */
export interface PortRow {
  id: string;
  name: string;
  country: string | null;
  iso3: string | null;
  date: string;
  age_days: number;
  stale: boolean;
  last: number | null;
  avg7: number | null;
  base: number | null;
  chg_pct: number | null;
  tanker: number | null;
  container: number | null;
  dry_bulk: number | null;
  imp7: number | null;
  exp7: number | null;
  n_days: number;
  base_days: number;
  lat: number | null;
  lon: number | null;
  locode: string | null;
  series: [string, number | null][];
}
export interface PortsPayload {
  rows: PortRow[];
  newest: string;
  /** "top" = the 25 busiest ports; "search" = ports matching `query`. */
  mode: "top" | "search";
  query: string;
  /** Matching ports the daily layer has no rows for (listed by PortWatch, nothing to show). */
  no_daily_rows: number;
  note: string;
}
/** WETR: Open-Meteo forecast day (temperatures in C, degree days in F-days). */
export interface WxDay {
  date: string;
  tmax: number | null;
  tmin: number | null;
  tmean: number | null;
  precip: number | null;
  wind: number | null;
  code: number | null;
  sky: string | null;
  hdd: number | null;
  cdd: number | null;
}
export interface WxForecast {
  lat: number | null;
  lon: number | null;
  tz: string | null;
  days: WxDay[];
  hdd: number;
  cdd: number;
  days_counted: number;
}
export interface WxBasketRow {
  city: string;
  hdd: number;
  cdd: number;
  days: number;
  tmean: number | null;
  tmax: number | null;
  tmin: number | null;
}
export interface WxAlert {
  event: string;
  severity: string;
  urgency: string | null;
  area: string | null;
  headline: string | null;
  onset: string | null;
  ends: string | null;
}
export interface WetrPayload {
  basket: { rows: WxBasketRow[]; average: { hdd: number; cdd: number } | null; weighting: string };
  place: { name: string; lat: number; lon: number; cc?: string | null; tz?: string | null; others?: string[] } | null;
  forecast: WxForecast | null;
  alerts: { status: "OK" | "NONE" | "SKIPPED" | "UNAVAILABLE" | "OUTSIDE"; items: WxAlert[]; note: string | null } | null;
  base_f: number;
  note: string;
}

/** Market-light holidays (`basis`: NYSE rules, Nager public holidays, or `fixed` = NSE partial rules without festivals). */
export interface HolidayCalendar {
  mkt: string;
  year: number;
  basis: "rules" | "public" | "fixed";
  label: string;
  holidays: { date: string; name: string; national: boolean }[];
  early: { date: string; name: string }[];
  source: string;
}

/** PRED (Phase 19 step 8): prediction-market rows. `prob` is 0..1; Polymarket volume is USD, Kalshi's is contracts of US$1. */
export interface PredRow {
  id: string;
  source: "polymarket" | "kalshi";
  question: string;
  outcome: string;
  prob: number;
  pct: number;
  volume: number;
  vol_unit: "USD" | "contracts";
  close: string | null;
  history: boolean;
  ref: string;
  event: string | null;
  basis?: string;
}
export interface PredPayload {
  rows: PredRow[];
  label: string;
  q: string;
  counts: Record<string, number>;
  failed: { source: string; reason: string }[];
  notes: string[];
  sources: string[];
  unit_note: string;
}
export interface PredOutcome {
  name: string;
  prob: number | null;
  pct: number | null;
  bid: number | null;
  ask: number | null;
}
export interface PredDetail {
  source: "polymarket" | "kalshi";
  id: string;
  question: string;
  label: string;
  open: boolean;
  volume: number;
  vol_unit: "USD" | "contracts";
  liquidity: number | null;
  open_interest?: number | null;
  close: string | null;
  series?: string;
  outcomes: PredOutcome[];
  lead: string;
  history: { t: number[]; p: number[] } | null;
  history_outcome: string;
  history_note: string | null;
  basis: string;
}

/** Phase 19 step 7: CDEP / FUND / LIQ / STBL / DEFI (`/api/world/cdep|fund|liq|stbl|defi`). Ladder rows are [price, qty, cumulative qty, cumulative notional]. */
export interface CdepBand { pct: number; bid: number; ask: number; imbalance_pct: number | null }
export interface CdepPayload {
  base: string; quote: string; symbol: string; venue: string; ts_ms: number | null; usd: boolean;
  bids: [number, number, number, number][]; asks: [number, number, number, number][];
  best_bid: number; best_ask: number; mid: number; spread: number; spread_pct: number; imbalance_pct: number;
  bid_qty: number; ask_qty: number; levels: [number, number]; bands: CdepBand[];
}
export interface FundRow {
  sym: string; base: string; kind: "PERP" | "QUARTERLY"; mark: number | null; index: number | null; basis_pct: number | null;
  rate_pct: number | null; interval_h: number | null; ann_pct: number | null; next_ms: number | null;
  expiry: string | null; days: number | null; ann_basis_pct: number | null; source: string;
}
export interface FundHistory { prints: { t: number; rate_pct: number; ann_pct: number }[]; interval_h: number; mean_rate_pct: number | null; mean_ann_pct: number | null }
export interface FundPayload { mode: "BOARD" | "DETAIL"; rows: FundRow[]; detail: FundHistory | null; venue: string | null; majors: string[] }
export interface LiqEvent { t: number; side: "LONG" | "SHORT"; px: number; base: number; usd: number; inst: string }
export interface LiqPayload {
  base: string; venue: string; events: number; span_s: number; since_ms: number | null; until_ms: number | null;
  long: { n: number; usd: number }; short: { n: number; usd: number }; largest: LiqEvent | null; recent: LiqEvent[]; ct_val: number; note: string;
}
export interface StblCoin {
  name: string; symbol: string; peg: string; mechanism: string | null; circulating: number; value: number | null;
  chg_1d: number | null; chg_7d: number | null; chg_30d: number | null; price: number | null; peg_dev_pct: number | null; chains: string[];
}
export interface StblPayload { coins: StblCoin[]; chains: { chain: string; usd: number; share_pct: number | null }[]; total_usd: number; n_coins: number; chain: string | null }
export interface DefiPool {
  chain: string; project: string; symbol: string; tvl: number; apy: number; apy_base: number | null; apy_reward: number | null;
  stable: boolean; il: string | null; apy_30d: number | null; pool: string;
}
export interface DefiPayload { rows: DefiPool[]; matched: number; mode: "ALL" | "CHAIN" | "PROJECT"; query: string | null; pools_over_tvl: number; min_tvl: number }

/** Phase 19 step 9: SECF fund rows from AMFI's NAVAll.txt (`/api/world/mfnav`). NAV is end of day per unit, not a market price. */
export interface MfItem {
  code: string; isin: string | null; isin_reinv: string | null; name: string; plan: string | null; option: string | null;
  nav: number; date: string; category: string | null; amc: string | null;
}
export interface MfNavPayload { query: string; items: MfItem[]; total: number; shown: number; nav_date: string | null; schemes: number; note: string }

/** TRADE (UN Comtrade): one row per year, US dollars. A flow the reporter has not filed is null, never zero. */
export interface TradeRow {
  year: number;
  exports: number | null;
  imports: number | null;
  total: number | null;
  balance: number | null;
}
export interface TradePayload {
  reporter: { iso: string; name: string };
  partner: { iso: string; name: string };
  cmd: string;
  cmd_desc: string;
  unit: string;
  rows: TradeRow[];
  source: string;
  note: string;
}
/** USMAC (BLS, BEA, Census): one series per row, each with its own latest period. `points` is oldest first; null = no value published. */
export interface UsSeries {
  id: string;
  alias: string;
  label: string;
  unit: string;
  freq: string;
  last: number | null;
  last_period: string | null;
  prev: number | null;
  prev_period: string | null;
  chg: number | null;
  chg_pct: number | null;
  notes: string[];
  points: [string, number | null][];
}
export interface UsMacroPayload {
  src: "BLS" | "BEA" | "CENSUS";
  series: UsSeries[];
  missing: string[];
  messages: string[];
  source: string;
  note: string;
}

/** UKCO (`/api/world/ukco`): UK Companies House. `mode` SEARCH lists companies; COMPANY has the profile, officers and filings (null = not loaded, see notes). */
export interface UkcoSearchRow { number: string; name: string | null; status: string | null; type: string | null; created: string | null; ceased: string | null; address: string }
export interface UkcoProfile {
  number: string; name: string | null; status: string | null; status_detail: string | null; type: string | null; subtype: string | null;
  created: string | null; ceased: string | null; jurisdiction: string | null; sic: string[]; address: string;
  accounts: { last_made_up_to: string | null; next_due: string | null; overdue: boolean | null };
  confirmation: { last_made_up_to: string | null; next_due: string | null; overdue: boolean | null };
  has_charges: boolean | null; has_insolvency_history: boolean | null;
}
export interface UkcoOfficer { name: string | null; role: string; appointed: string | null; resigned: string | null; nationality: string | null; occupation: string | null; country: string | null }
export interface UkcoFiling { date: string | null; category: string; type: string | null; description: string; pages: number | null; paper: boolean }
export type UkcoPayload =
  | { mode: "SEARCH"; query: string; total: number | null; items: UkcoSearchRow[]; note: string }
  | {
      mode: "COMPANY"; number: string; profile: UkcoProfile; notes: string[]; note: string;
      officers: { total: number | null; active: number | null; resigned: number | null; items: UkcoOfficer[] } | null;
      filings: { total: number | null; items: UkcoFiling[] } | null;
    };

/** ADDR (`/api/world/addr`): an EVM address's balance and latest transactions, and the gas oracle (Etherscan V2). Amounts are in the chain's native coin. */
export interface AddrTx { hash: string; block: number | null; time: number | null; dir: "IN" | "OUT" | "SELF" | "CREATE"; from: string | null; to: string | null; value: number; fee: number | null; failed: boolean; method: string; confirmations: number | null }
export interface AddrGas { last_block: number | null; safe: number | null; propose: number | null; fast: number | null; base_fee: number | null }
export interface AddrPayload {
  mode: "ADDRESS" | "GAS"; chain: string; chainid: number; coin: string; address: string | null; note: string; notes: string[];
  balance: { wei: string; balance: number } | null; txs: AddrTx[] | null; gas: AddrGas | null;
}

/** AIS (`/api/world/ais`): ship positions in a chokepoint box from AISstream (free key AISSTREAM_API_KEY). Positions are as reported by ships. */
export interface AisRow {
  mmsi: number; name: string; imo: number | null; type: string; type_code: number | null;
  sog: number | null; cog: number | null; heading: number | null; nav: number | null; nav_name: string;
  dest: string | null; eta: string | null; length: number | null; draught: number | null;
  lat: number; lon: number; seen: number; static_age_s: number | null;
}
export interface AisPayload {
  area: string; box: [number, number, number, number]; rows: AisRow[]; truncated: number;
  received: number; capped: boolean; listened_s: number; fixture: boolean; note: string;
}

export const worldApi = {
  trade: (reporter: string, partner: string, hs: string, years: number, fresh = false) =>
    request<Envelope<TradePayload>>(`/api/world/trade?${qs({ reporter, partner, hs, years: String(years) })}`, fresh ? 0 : 600_000),
  usmac: (src: string, q: string, years: number, fresh = false) =>
    request<Envelope<UsMacroPayload>>(`/api/world/usmac?${qs({ src, q, years: String(years) })}`, fresh ? 0 : 600_000),
  stats: (country: string, ind: string, fresh = false) => request<Envelope<WorldSeries>>(`/api/world/stats?${qs({ country, ind })}`, fresh ? 0 : 600_000),
  dbsearch: (q: string, dataset: string, offset: number, fresh = false) =>
    request<Envelope<DbsPayload>>(`/api/world/dbsearch?${qs({ q, dataset, offset: String(offset) })}`, fresh ? 0 : 600_000),
  weco: (fresh = false) => request<Envelope<WecoPayload>>("/api/world/weco", fresh ? 0 : 600_000),
  cenb: (fresh = false) => request<Envelope<CenbPayload>>("/api/world/cenb", fresh ? 0 : 300_000),
  nrg: (fresh = false) => request<Envelope<NrgPayload>>("/api/world/nrg", fresh ? 0 : 300_000),
  ship: (fresh = false) => request<Envelope<ShipPayload>>("/api/world/ship", fresh ? 0 : 300_000),
  ports: (q: string, fresh = false) => request<Envelope<PortsPayload>>(`/api/world/ports?${qs({ q })}`, fresh ? 0 : 300_000),
  wetr: (place: string, fresh = false) => request<Envelope<WetrPayload>>(`/api/world/wetr?${qs({ place })}`, fresh ? 0 : 300_000),
  holidays: (mkt: string, year: number) => request<Envelope<HolidayCalendar>>(`/api/world/holidays?${qs({ mkt, year: String(year) })}`, 3_600_000),
  pred: (q: string, fresh = false) => request<Envelope<PredPayload>>(`/api/world/pred?${qs({ q })}`, fresh ? 0 : 60_000),
  predDetail: (source: string, id: string, fresh = false) => request<Envelope<PredDetail>>(`/api/world/pred/detail?${qs({ source, id })}`, fresh ? 0 : 60_000),
  cdep: (pair: string, fresh = false) => request<Envelope<CdepPayload>>(`/api/world/cdep?${qs({ pair })}`, fresh ? 0 : 4_000),
  fund: (sym: string, fresh = false) => request<Envelope<FundPayload>>(`/api/world/fund?${qs({ sym })}`, fresh ? 0 : 30_000),
  liq: (sym: string, fresh = false) => request<Envelope<LiqPayload>>(`/api/world/liq?${qs({ sym })}`, fresh ? 0 : 20_000),
  stbl: (chain: string, fresh = false) => request<Envelope<StblPayload>>(`/api/world/stbl?${qs({ chain })}`, fresh ? 0 : 600_000),
  defi: (q: string, fresh = false) => request<Envelope<DefiPayload>>(`/api/world/defi?${qs({ q })}`, fresh ? 0 : 600_000),
  mfnav: (q: string, fresh = false) => request<Envelope<MfNavPayload>>(`/api/world/mfnav?${qs({ q })}`, fresh ? 0 : 3_600_000),
  figi: (q: string, fresh = false) => request<Envelope<FigiResult>>(`/api/world/figi?${qs({ q })}`, fresh ? 0 : 600_000),
  ukco: (q: string, fresh = false) => request<Envelope<UkcoPayload>>(`/api/world/ukco?${qs({ q })}`, fresh ? 0 : 300_000),
  addr: (q: string, fresh = false) => request<Envelope<AddrPayload>>(`/api/world/addr?${qs({ q })}`, fresh ? 0 : 15_000),
  /** One listen takes about 8 s on the server (cached 20 s there); the client cache is short so F5 really listens again. */
  ais: (q: string, fresh = false) => request<Envelope<AisPayload>>(`/api/world/ais?${qs({ q })}`, fresh ? 0 : 15_000),
  ticks: (symbol: string, bar: string) => request<Envelope<TickBars>>(`/api/world/ticks/${encodeURIComponent(symbol)}?${qs({ bar })}`, 0),
  /** GP `EVT`: earnings (last four reported), ex-dividend dates and splits. */
  events: (symbol: string, fresh = false) =>
    request<Envelope<ChartEvents>>(`/api/world/events?${qs({ symbol })}`, fresh ? 0 : 120_000),
  drawings: (symbol: string) => send<{ symbol: string; drawings: unknown[]; updated_at: number | null }>("GET", `/api/drawings/${encodeURIComponent(symbol)}`),
  saveDrawings: (symbol: string, drawings: unknown[]) =>
    send<{ symbol: string; drawings: unknown[]; updated_at: number }>("PUT", `/api/drawings/${encodeURIComponent(symbol)}`, { drawings }),
};

// --- Phase 17: alert delivery (DLVR) and the daily brief (BRIEF) ---
export type DeliveryChannel = "email" | "telegram" | "webhook" | "desktop";

/** The delivery settings document (backend/openterm/delivery/settings.py). Secrets are never here: they live in APIKEYS. */
export interface DeliverySettings {
  channels: Record<DeliveryChannel, boolean>;
  email_to: string;
  telegram_chat_id: string;
  brief: { enabled: boolean; time: string; days: string; tz: string };
}
/** GET / PUT /api/delivery. `status` is per push channel: "off" | "ready" | "KEY REQUIRED: ..." (desktop has none). */
export interface DeliveryPayload {
  settings: DeliverySettings;
  status: Partial<Record<DeliveryChannel, string>>;
}
/** One row of the delivery log (a send attempt). */
export interface DeliveryRow {
  id: number;
  at: number;
  kind: string;
  ref: string;
  channel: string;
  status: string;
  detail: string | null;
}
/** A partial settings change; the backend merges it over the saved document. */
export type DeliveryPatch = Partial<Omit<DeliverySettings, "channels" | "brief">> & {
  channels?: Partial<Record<DeliveryChannel, boolean>>;
  brief?: Partial<DeliverySettings["brief"]>;
};

export const deliveryApi = {
  get: () => send<DeliveryPayload>("GET", "/api/delivery"),
  put: (patch: DeliveryPatch) => send<DeliveryPayload>("PUT", "/api/delivery", patch),
  log: (limit = 100) => send<{ deliveries: DeliveryRow[] }>("GET", `/api/delivery/log?limit=${limit}`),
  test: (channel: Exclude<DeliveryChannel, "desktop">) => send<{ results: DeliveryRow[] }>("POST", "/api/delivery/test", { channel }),
};

export interface BriefSection {
  id: string;
  title: string;
  source: string | null;
  age_s: number | null;
  stale: boolean;
  error: string | null;
  lines: string[];
}
export interface Brief {
  at: number;
  sections: BriefSection[];
  watchlist?: string;
}
export const briefApi = {
  get: () => send<{ brief: Brief | null }>("GET", "/api/brief"),
  run: (sendIt: boolean) => send<{ brief: Brief; delivered: DeliveryRow[] | null }>("POST", `/api/brief/run?send=${sendIt ? 1 : 0}`),
};
