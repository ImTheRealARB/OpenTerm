/**
 * Payload types for every backend route the browser calls. TYPE-ONLY: this file has no runtime code and imports nothing
 * that runs, so pure modules (and vitest, which has no `window`) can import from it without pulling in the request layer.
 * Import with `import type { ... } from "../net/types"`. The clients that fetch these live next to it (marketApi.ts, secApi.ts, ...).
 */

// ---------------------------------------------------------------------------
// Shared envelope and market data
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// API keys and AI spend (keysApi)
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Indicator presets (presetsApi)
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Watchlists (workspaceApi)
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// News (marketApi.news)
// ---------------------------------------------------------------------------

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
  kind: "top" | "symbol" | "keyword" | "pool";
  query: string | null;
  items: NewsItem[];
  /** Feeds that did not answer this time (top stories and feed filters). */
  failed: string[];
  /** Feed filters only: how many of the asked-for feeds answered, and how many were asked. */
  feeds_ok?: number;
  feeds_total?: number;
}

// ---------------------------------------------------------------------------
// Movers and the crypto board (marketApi)
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Layouts (workspaceApi)
// ---------------------------------------------------------------------------

export interface LayoutInfo {
  name: string;
  panels: number;
  updated_at: number;
}

// ---------------------------------------------------------------------------
// Provider health and the server log (systemApi)
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Macro (macroApi)
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Portfolios (portfolioApi)
// ---------------------------------------------------------------------------

export interface Position {
  symbol: string;
  qty: number;
  cost: number | null;
  currency: string | null;
  notes: string | null;
  /** Set on lots written by a read-only broker sync ("kite" | "ibkr"); absent on manual lots. */
  source?: string;
  synced_at?: number;
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

// ---------------------------------------------------------------------------
// Price alerts (priceAlertsApi)
// ---------------------------------------------------------------------------

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
  /** The `VIA` channels this alert asked for ("telegram" | "email" | "webhook"); null = every channel switched on in DELIVERY. */
  channels: string[] | null;
}

/** What the backend alert engine reports (Phase 20). It owns firing, so this is where limits and refused matches show. */
export interface AlertEngineState {
  running: boolean;
  /** Fixed text: "ACTIVE WHILE OPENTERM RUNNING". */
  note: string;
  watching: string[];
  last_tick_age_s: number | null;
  last_news_poll_age_s: number | null;
  /** Fixture mode: the engine refuses every tick and headline, so this browser fires on the recorded data instead. */
  fixtures: boolean;
  /** Matches the engine refused to act on (SYNTHETIC / STALE / FIXTURE MODE / news outage), with the reason. */
  skipped: { key: string; label: string; reason: string; age_s: number }[];
}

// ---------------------------------------------------------------------------
// Screener and peers (marketApi)
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Settings (settingsApi)
// ---------------------------------------------------------------------------

export interface SettingsDoc {
  version: number;
  /** null until the first save. */
  settings: Record<string, unknown> | null;
  updated_at: number | null;
}

// ---------------------------------------------------------------------------
// Backtesting (btApi)
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Portfolio valuations (portfolioApi)
// ---------------------------------------------------------------------------

/** Phase 15: quant jobs (RISK, PORT OPT, PORT ATTR, ...). The answer is the job; its `result` is an envelope of a table payload. */
export interface ValRow {
  date: string;
  value: number;
  flow: number;
}

// ---------------------------------------------------------------------------
// Kite Connect (kiteApi)
// ---------------------------------------------------------------------------

/** Phase 15: Kite Connect (read-only data source). Login is `/api/kite/login`, opened in a new tab; the api key never reaches this app. */
export interface KiteStatus {
  state: string;
  message?: string | null;
  user?: string | null;
  logged_in_at?: string | null;
  expires_note?: string | null;
}

// ---------------------------------------------------------------------------
// News alerts (newsAlertsApi)
// ---------------------------------------------------------------------------

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
  /** The `VIA` channels this alert asked for; null = every channel switched on in DELIVERY. */
  channels: string[] | null;
}

// ---------------------------------------------------------------------------
// Chart events, tick bars and drawings (chartApi)
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// World data (worldApi)
// ---------------------------------------------------------------------------

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
  /** What the numbers are (mirror of seriesboard.KINDS in the backend). "rate" = already a percentage, so `chg` is in percentage
   *  points and `chg_pct` is null; "unknown" = a raw BLS id outside the catalogue (plain change, no percent). */
  kind: "level" | "rate" | "unknown";
  freq: string;
  last: number | null;
  last_period: string | null;
  prev: number | null;
  prev_period: string | null;
  chg: number | null;
  /** Percent change of a "level" series only; null for a "rate" or "unknown" series (and when the previous value is zero). */
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

/**
 * FLT (`/api/world/flt`): live aircraft from the OpenSky Network, as reported by transponders (ADS-B); coverage is partial. Anonymous works (limited credits);
 * `authenticated` says whether an OpenSky login (APIKEYS) was used. Altitude/speed/climb come in both source units (m, m/s) and display units (ft, kt, ft/min).
 * `seen` = epoch seconds of the position report; a MAP layer needs only lat, lon, heading and seen.
 */
export interface FltRow {
  icao24: string; callsign: string; country: string; lat: number; lon: number;
  alt_m: number | null; geo_alt_m: number | null; alt_ft: number | null;
  speed_ms: number | null; speed_kt: number | null; heading: number | null;
  vrate_ms: number | null; vrate_fpm: number | null;
  on_ground: boolean; squawk: string; spi: boolean; source: string; seen: number | null; age_s: number | null;
}

export interface FltPayload {
  area: string; kind: "AREA" | "BOX" | "CALLSIGN"; box: [number, number, number, number] | null; rows: FltRow[]; truncated: number;
  received: number; no_position: number; source_time: number; credits_cost: number; credits_remaining: number | null;
  authenticated: boolean; access: string; note: string; country_note: string; fixture: boolean;
}

/** AIS (`/api/world/ais`): ship positions in a chokepoint box from AISstream (free key AISSTREAM_API_KEY). Positions are as reported by ships. */
export interface AisRow {
  mmsi: number; name: string; imo: number | null; type: string; type_code: number | null;
  sog: number | null; cog: number | null; heading: number | null; nav: number | null; nav_name: string;
  dest: string | null; eta: string | null; length: number | null; draught: number | null;
  lat: number; lon: number; seen: number; static_age_s: number | null;
  /** true = position kept from an EARLIER listen (server memory, at most `memory_s` old); false = heard during this listen. */
  remembered: boolean;
  /** Seconds since the position report itself, as of the listen. */
  age_s: number;
}

export interface AisPayload {
  area: string; box: [number, number, number, number]; rows: AisRow[]; truncated: number;
  received: number; capped: boolean; listened_s: number; fixture: boolean; note: string;
  /** How many ships came from memory, and the memory's age limit in seconds (300). */
  remembered: number; memory_s: number;
}

/** MAP layers (`/api/world/geo/...`): positions as lat/lon degrees and times as epoch seconds. */
export interface GeoQuake {
  id: string; lat: number; lon: number; depth_km: number | null; mag: number | null; mag_type: string | null;
  place: string; time: number; url: string | null; tsunami: boolean; alert: string | null; status: string | null;
}

export interface GeoQuakes { rows: GeoQuake[]; skipped: number; title: string; generated: number | null; note: string }

export interface GeoEvent {
  id: string; title: string; category: string; category_title: string; lat: number; lon: number; time: number;
  mag: number | null; mag_unit: string | null; source: string | null; url: string | null; track: [number, number][];
}

export interface GeoEvents { rows: GeoEvent[]; skipped: number; title: string; note: string }

export interface GeoPort {
  id: string; name: string; country: string | null; locode: string | null; lat: number; lon: number; rank: number;
  calls_per_day: number; newest: string;
}

export interface GeoPorts { rows: GeoPort[]; skipped: number; newest: string; note: string }

export interface GeoChokepoint { id: string; name: string; box: [number, number, number, number]; lat: number; lon: number }

export interface GeoChokepoints { rows: GeoChokepoint[]; note: string }

/**
 * MF (`/api/world/mf`): Indian mutual funds from MFapi.in (community service, data from AMFI, not an official AMFI API). `mode` SEARCH lists scheme names;
 * FUND is one scheme: its latest NAV, the returns table and the whole NAV series (`t` epoch seconds, `v` NAV, oldest first).
 * A return with `pct: null` has no number on purpose (`why` says why): the history is shorter than the period, or has a hole there.
 */
export interface MfSearchRow { code: number; name: string }

export interface MfSearch { mode: "SEARCH"; query: string; items: MfSearchRow[]; total: number; shown: number; note: string; source_note: string }

export interface MfReturnRow {
  period: string;
  kind: "ABSOLUTE RETURN" | "CAGR";
  target: string;
  base_date: string | null;
  base_nav: number | null;
  pct: number | null;
  why: string | null;
}

export interface MfFund {
  mode: "FUND"; code: number; name: string; fund_house: string; scheme_type: string; category: string;
  isin_growth: string | null; isin_div: string | null;
  latest: { date: string; nav: number }; first_date: string; points: number;
  returns: MfReturnRow[]; t: number[]; v: number[]; payout_plan: boolean; note: string; source_note: string;
}

export type MfPayload = MfSearch | MfFund;

/**
 * USASP / FEDREG / FEC / CONGRESS (`/api/world/usasp|fedreg|fec|congress`): US government data. USASP and FEDREG are keyless and were run live; FEC and
 * CONGRESS need a free api.data.gov key (424 KEY REQUIRED without it) and are DOC-SHAPED (never run against a live key).
 */
export interface UsaspRecipient { name: string; uei: string | null; amount: number | null }

export interface UsaspAward { award_id: string; recipient: string; amount: number | null; agency: string; start: string | null; end: string | null; description: string }

export interface UsaspAgency { name: string; code: string | null; amount: number | null }

export type UsaspPayload =
  | { mode: "KEYWORD"; query: string; window: string; award_kind: string; recipients: UsaspRecipient[]; recipients_total: number | null; awards: UsaspAward[] | null; notes: string[]; note: string }
  | { mode: "AGENCY"; window: string; award_kind: string; agencies: UsaspAgency[]; note: string }
  | { mode: "AGENCY_RECIPIENTS"; agency: string; window: string; award_kind: string; recipients: UsaspRecipient[]; recipients_total: number | null; note: string };

export interface FedregItem { number: string; title: string; type: string; agencies: string[]; date: string | null; abstract: string | null; url: string | null }

export interface FedregPayload { query: string; type: string | null; total: number; shown: number; items: FedregItem[]; note: string }

export interface FecItem { kind: "CANDIDATE" | "COMMITTEE"; id: string; name: string; party: string | null; office: string | null; state: string | null; district: string | null; last_year: number | null }

export interface FecCycle { cycle: number; receipts: number | null; disbursements: number | null; cash: number | null; debts: number | null; individual: number | null; covered_to: string | null }

export type FecPayload =
  | { mode: "SEARCH"; query: string; items: FecItem[]; notes: string[]; note: string }
  | { mode: "CANDIDATE" | "COMMITTEE"; id: string; name: string | null; cycles: FecCycle[]; latest: FecCycle | null; note: string };

export interface CongressRow { congress: number; type: string; number: string; title: string; chamber: string | null; action_date: string | null; action: string; updated: string | null }

export type CongressPayload =
  | { mode: "LATEST" | "TITLE FILTER"; query: string; fetched: number; matched: number; items: CongressRow[]; note: string }
  | { mode: "BILL"; congress: number; type: string; number: string; title: string; chamber: string | null; introduced: string | null; sponsors: string[];
      cosponsors: number | null; policy_area: string | null; action_date: string | null; action: string; updated: string | null; note: string };

// ---------------------------------------------------------------------------
// Alert delivery (deliveryApi)
// ---------------------------------------------------------------------------

export type DeliveryChannel = "email" | "telegram" | "webhook" | "desktop";

/** Who a channel writes to, as the browser may know it: whether it is set, and a masked hint. Never the value itself. */
export interface DeliveryRecipient {
  configured: boolean;
  hint: string;
}

/**
 * The delivery settings the browser receives (backend/openterm/delivery/settings.py `public`). Secrets are never here
 * (they live in APIKEYS) and neither are the recipient address or Telegram chat id: only `recipients` hints.
 */
export interface DeliverySettings {
  channels: Record<DeliveryChannel, boolean>;
  recipients: { email: DeliveryRecipient; telegram: DeliveryRecipient };
  daily_cap: number;
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

/**
 * A partial settings change; the backend merges it over the saved document. `email_to` / `telegram_chat_id` are
 * write-only: a non-empty value replaces the stored one, an empty one keeps it (the browser never reads them back).
 */
export type DeliveryPatch = {
  email_to?: string;
  telegram_chat_id?: string;
  daily_cap?: number;
  channels?: Partial<Record<DeliveryChannel, boolean>>;
  brief?: Partial<DeliverySettings["brief"]>;
};

/** `POST /api/delivery/telegram/pair/start`: the bot's link and the one-time code to send it. */
export interface TelegramPairStart {
  bot: string;
  link: string;
  code: string;
  expires_in: number;
}

/** `POST .../pair/check`: `paired: true` once the code arrived (the chat id stays on the server). */
export interface TelegramPairCheck {
  paired: boolean;
  expires_in?: number;
}

// ---------------------------------------------------------------------------
// Daily brief (briefApi)
// ---------------------------------------------------------------------------

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
