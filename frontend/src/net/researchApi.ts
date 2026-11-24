/** Table-shaped research functions: one call per family, `fn` is the backend route name. `fresh` (F5) skips the client cache. */
import type { TablePayload } from "../research/tablePayload";
import { get, TTL } from "./core";
import { filingsApi } from "./filingsApi";
import type { ConePoint } from "../chart/cone";
import type { Envelope } from "./types";

type Params = Record<string, string | undefined>;

export const researchApi = {
  /** EE, EEO, ANR, MGMT, IPO, ... (`/api/research/<fn>`). */
  get: (fn: string, params: Params, fresh = false) => get<Envelope<TablePayload>>(`/api/research/${fn}`, params, TTL.m2, fresh),
  /** DCF, WACC, RV (`/api/valuation/<fn>`). */
  valuation: (fn: string, params: Params, fresh = false) => get<Envelope<TablePayload>>(`/api/valuation/${fn}`, params, TTL.s30, fresh),
  /** Options, rates, futures (OMON, OV, OSA, YAS, CT, COT, ...). */
  deriv: (fn: string, params: Params, fresh = false) => get<Envelope<TablePayload>>(`/api/deriv/${fn}`, params, TTL.m1, fresh),
  /** GP CONE (Phase 28): per-expiry 1 and 2 SD ranges from ATM IV. */
  cone: (symbol: string) =>
    get<Envelope<{ symbol: string; spot: number; label: string; points: ConePoint[] }>>("/api/deriv/cone", { symbol }, TTL.m1),
  /** Phase 29 fundamentals depth: GF EM DDIS SCORE FRM EQSBT IBQ REVS (`/api/fund/<fn>`). Filings change slowly: 2 minutes. */
  fund: (fn: string, params: Params, fresh = false) => get<Envelope<TablePayload>>(`/api/fund/${fn}`, params, TTL.m2, fresh),
  /** Phase 29 filings: FTS MA LEGAL BIO RELS ESG (`/api/filings/<fn>`, the client lives in filingsApi.ts). */
  filings: filingsApi.get,
  /** Non-US curves, credit spreads and auctions (RATES views). */
  rates: (fn: string, params: Params, fresh = false) => get<Envelope<TablePayload>>(`/api/rates/${fn}`, params, TTL.m1, fresh),
};
