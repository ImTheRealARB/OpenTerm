/**
 * Payload types of the order flow panels TAS / BIGT / FOOT (`/api/world/flow/...`). Type-only (no runtime code), so vitest can import
 * it. Mirrors `backend/openterm/world/orderflow.py` and `world/flow.py`.
 */

/** One aggregated exchange trade. `side` is the AGGRESSOR: BUY = bought at the ask, SELL = sold into the bid. */
export interface FlowTrade {
  id: number;
  /** ms since the epoch, the exchange's clock */
  t: number;
  p: number;
  /** base coins */
  q: number;
  /** price x coins in the QUOTE currency (USD for USDT / USDC / USD pairs) */
  value: number;
  side: "BUY" | "SELL";
}

/** Fields every flow answer shares. */
export interface FlowHead {
  symbol: string;
  pair: string;
  base: string;
  quote: string;
  quote_is_usd: boolean;
  venue: string;
  /** "EXACT (EXCHANGE TRADES)": the exchange says who the aggressor was. */
  basis: string;
  /** trades held (the answer was built from these) */
  n: number;
  /** seconds between the oldest and newest trade held */
  span_s: number;
  newest_t: number;
}

export interface TasPayload extends FlowHead {
  rows: FlowTrade[];
}

export interface BigTradesPayload extends FlowHead {
  rows: FlowTrade[];
  /** matches before the 500-row cap */
  found: number;
  /** trades looked at */
  scanned: number;
  filter: { min_qty: number | null; usd: number | null };
}

/** [level index into `levels`, bid volume (aggressor sells), ask volume (aggressor buys), imbalance flag: 1 = ask side, 2 = bid side] */
export type FootCell = [number, number, number, number];

export interface FootBar {
  t: number;
  o: number;
  h: number;
  l: number;
  c: number;
  bid: number;
  ask: number;
  vol: number;
  /** ask - bid */
  delta: number;
  cum_delta: number;
  /** price with the most volume in this bar */
  poc: number;
  cells: FootCell[];
  /** true when older trades were not fetched, so this bar misses its start */
  partial: boolean;
}

export interface FootprintPayload extends FlowHead {
  interval: string;
  interval_ms: number;
  bars_asked: number;
  /** trades did not reach back over the whole window */
  truncated: boolean;
  step: number;
  /** ascending prices, one per row of the ladder */
  levels: number[];
  bars: FootBar[];
  cum_delta: number[];
}
