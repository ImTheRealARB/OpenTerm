/** Macro data: FRED series, MACRO search, the US yield curve, earnings and the economic calendar (FRED, MACRO, RATES, ERN, ECO). */
import { get, TTL } from "./core";
import type { Envelope, EarningsPayload, EcoPayload, FredSeries, MacroPayload, YieldCurve } from "./types";

export const macroApi = {
  fred: (id: string, range: string, fresh = false) => get<Envelope<FredSeries>>("/api/fred", { id, range }, TTL.m1, fresh),
  macro: (q: string, fresh = false) => get<Envelope<MacroPayload>>("/api/macro", { q }, TTL.m1, fresh),
  rates: (fresh = false) => get<Envelope<YieldCurve>>("/api/rates", undefined, TTL.m1, fresh),
  earnings: (date: string, fresh = false) => get<Envelope<EarningsPayload>>("/api/earnings", { date }, TTL.s30, fresh),
  eco: (start: string | null, days: number, fresh = false) =>
    get<Envelope<EcoPayload>>("/api/eco", { start: start ?? undefined, days: String(days) }, TTL.m1, fresh),
};
