/**
 * Orders (Phase 18 step 1), loopback only. There is NO `mode`, `live` or `paper` field in any request: paper or live is decided by the
 * backend from the broker slot (alpaca-paper, alpaca-live, kite), and every order needs the one-time `token` the server issued for exactly
 * that order in `preview`. The AI has no route to any of this.
 */
import { send } from "./core";

export type OrderBroker = "alpaca-paper" | "alpaca-live" | "kite";
export type OrderMode = "paper" | "live";

export interface OrderBody {
  broker: OrderBroker;
  symbol: string;
  side: "buy" | "sell";
  qty: number;
  type: "market" | "limit" | "stop";
  tif: "day" | "gtc" | "ioc";
  limit_price?: number;
  stop_price?: number;
}

export interface Mandate {
  symbols: string[];
  max_shares: number;
  max_notional: number;
  max_gross: number;
  max_trades_per_day: number;
}

export interface BrokerRow {
  id: OrderBroker;
  label: string;
  slot_mode: OrderMode;
  ready: boolean;
  message: string | null;
  kind: string | null;
  note: string;
}

export interface OrdersStatus {
  kill: { on: boolean; at: number | null };
  live_enabled: boolean;
  mandate: Mandate;
  trades_today: number;
  brokers: BrokerRow[];
}

export interface Check {
  name: string;
  ok: boolean;
  detail: string;
}

export interface Account {
  broker: string;
  id: string;
  mode: OrderMode;
  currency: string;
  equity: number | null;
  cash: number | null;
  buying_power: number | null;
  status: string | null;
  host: string | null;
  note: string;
}

export interface Preview {
  order: OrderBody;
  line: string;
  replace: string | null;
  broker: OrderBroker;
  mode: OrderMode;
  account: Account;
  price: number | null;
  price_note: string | null;
  check: { ok: boolean; checks: Check[] };
  mandate: Mandate;
  note: string | null;
  /** Present only when the whole mandate check passes. Single use; void after `token_ttl_s` seconds. */
  token: string | null;
  token_ttl_s: number | null;
}

export interface BrokerOrder {
  id: string | null;
  client_id: string | null;
  symbol: string;
  side: string;
  qty: number | null;
  filled_qty: number;
  type: string | null;
  tif: string | null;
  limit_price: number | null;
  stop_price: number | null;
  status: string;
  avg_fill_price: number | null;
  submitted_at: string | null;
}

export interface Fill {
  fill_id: string;
  order_id: string | null;
  symbol: string;
  side: string;
  qty: number;
  price: number;
  at: string | null;
  currency: string;
}

export interface Position {
  symbol: string;
  qty: number;
  avg_cost: number | null;
  price: number | null;
  market_value: number | null;
}

export interface Blotter {
  broker: OrderBroker;
  account: Account;
  as_of: number;
  errors: Record<string, string>;
  open_orders: BrokerOrder[] | null;
  fills: Fill[] | null;
  positions: Position[] | null;
}

export interface KillResult {
  kill: { on: boolean; at: number | null };
  brokers: Record<string, { ok: boolean | null; detail: string; cancelled: number; failed: number }>;
}

export interface LedgerView {
  entries: { seq: number; at: number; event: string; broker: string; mode: string; ref: string; order: Partial<OrderBody>; reason: string | null; status: string | null }[];
  verify: { ok: boolean; count: number; broken_at: number | null; reason: string | null };
}

export const LIVE_PHRASE = "I UNDERSTAND LIVE ORDERS USE REAL MONEY";

export const ordersApi = {
  status: () => send<OrdersStatus>("GET", "/api/orders/status"),
  blotter: (broker: OrderBroker) => send<Blotter>("GET", `/api/orders/blotter?broker=${encodeURIComponent(broker)}`),
  ledger: () => send<LedgerView>("GET", "/api/orders/ledger"),
  preview: (order: OrderBody) => send<Preview>("POST", "/api/orders/preview", { order }),
  submit: (order: OrderBody, token: string) => send<{ order: BrokerOrder; client_id: string; mode: OrderMode; broker: OrderBroker }>("POST", "/api/orders/submit", { order, token }),
  cancel: (broker: OrderBroker, order_id: string) => send<{ cancelled: string }>("POST", "/api/orders/cancel", { broker, order_id }),
  kill: () => send<KillResult>("POST", "/api/orders/kill"),
  unkill: () => send<{ kill: { on: boolean } }>("POST", "/api/orders/unkill"),
  setLive: (on: boolean, phrase?: string) => send<{ live_enabled: boolean }>("PUT", "/api/orders/live", { on, phrase }),
  setMandate: (m: Mandate) => send<Mandate>("PUT", "/api/orders/mandate", m),
  importFills: (broker: OrderBroker, portfolio: string) => send<{ added: number; portfolio: string; detail: string }>("POST", "/api/orders/import", { broker, portfolio }),
};
