/** Order flow panels (TAS, BIGT, FOOT): Binance spot aggregated trades through `/api/world/flow/...`. */
import { get, TTL } from "./core";
import type { BigTradesPayload, FootprintPayload, TasPayload } from "./flowTypes";
import type { Envelope } from "./types";

export const flowApi = {
  trades: (sym: string, limit: number, fresh = false) =>
    get<Envelope<TasPayload>>("/api/world/flow/trades", { sym, limit: String(limit) }, TTL.s2, fresh),
  /** Exactly one of `min` (coins) or `usd` is sent; neither lets the server pick its default. */
  bigtrades: (sym: string, filter: { min?: number; usd?: number }, fresh = false) => {
    const q: Record<string, string> = { sym };
    if (filter.min !== undefined) q.min = String(filter.min);
    if (filter.usd !== undefined) q.usd = String(filter.usd);
    return get<Envelope<BigTradesPayload>>("/api/world/flow/bigtrades", q, TTL.s4, fresh);
  },
  footprint: (sym: string, interval: string, bars: number, fresh = false) =>
    get<Envelope<FootprintPayload>>("/api/world/flow/footprint", { sym, interval, bars: String(bars) }, TTL.s4, fresh),
};
