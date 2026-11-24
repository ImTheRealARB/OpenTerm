/** TRA and BETA (Phase 22): the server does the maths on daily bars; these are the two requests. */
import { get, TTL } from "./core";
import type { BetaPayload, TraPayload } from "./returnsTypes";
import type { Envelope } from "./types";

export const returnsApi = {
  tra: (symbols: string[], vs: string, range: string, fresh = false) =>
    get<Envelope<TraPayload>>("/api/world/tra", { symbols: symbols.join(","), vs, range }, TTL.m5, fresh),
  beta: (symbol: string, vs: string, range: string, per: string, win: number, fresh = false) =>
    get<Envelope<BetaPayload>>("/api/world/beta", { symbol, vs, range, per, win: String(win) }, TTL.m5, fresh),
};
