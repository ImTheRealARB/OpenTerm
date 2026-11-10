/** Read-only broker sync (Phase 18 step 2): Zerodha Kite holdings and Interactive Brokers (local Client Portal gateway) into PORT. */
import { send } from "./core";

export type Broker = "kite" | "ibkr";

export interface SyncDiff {
  added: string[];
  removed: string[];
  changed: { symbol: string; qty_from: number; qty_to: number; cost_from: number | null; cost_to: number | null }[];
}

export interface SyncRecord {
  broker: Broker;
  portfolio: string;
  /** Unix seconds. */
  at: number;
  ok: boolean;
  error: string | null;
  kind?: string;
  base?: string;
  counts: { fetched: number; imported: number; skipped: number; conflicts: number; manual_kept: number; previous: number } | null;
  diff: SyncDiff | null;
  skipped: { symbol: string; reason: string; account?: string }[];
  conflicts: string[];
  warnings: string[];
  /** IBKR only. */
  accounts?: string[];
  cash?: { account: string; rows: { currency: string; base: boolean; cash: number | null; settled: number | null; net_liq: number | null }[] }[];
  /** Kite only. */
  holdings?: number;
  positions?: number;
}

export interface BrokerStatus {
  broker: Broker;
  last: SyncRecord | null;
  last_ok: SyncRecord | null;
  last_error: SyncRecord | null;
  runs: number;
  login?: { state: string; message?: string | null } | null;
  gateway_url?: string;
}

export interface SyncStatus {
  kite: BrokerStatus;
  ibkr: BrokerStatus;
  default_portfolio: Record<Broker, string>;
}

export const syncApi = {
  status: () => send<SyncStatus>("GET", "/api/sync/status"),
  kite: (portfolio?: string, positions?: boolean) => send<SyncRecord>("POST", "/api/sync/kite", { portfolio, positions }),
  ibkr: (portfolio?: string, account?: string) => send<SyncRecord>("POST", "/api/sync/ibkr", { portfolio, account }),
  ibkrCheck: () => send<{ authenticated: boolean; gateway_url: string }>("GET", "/api/sync/ibkr/check"),
  setGateway: (gateway_url: string) => send<{ gateway_url: string }>("PUT", "/api/sync/ibkr/settings", { gateway_url }),
};
