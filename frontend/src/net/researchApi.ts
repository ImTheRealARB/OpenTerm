/** Table-shaped research functions: one call per family, `fn` is the backend route name. `fresh` (F5) skips the client cache. */
import type { TablePayload } from "../research/tablePayload";
import { get, TTL } from "./core";
import { filingsApi } from "./filingsApi";
import type { ConePoint } from "../chart/cone";
import type { Envelope, EqsFundPayload } from "./types";

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
  /** EQS formula fields (MARGIN OPMARGIN ROE GROWTH DE) for every screener name that files with the SEC. One call, cached a day server side. */
  eqsFund: (fresh = false) => get<Envelope<EqsFundPayload>>("/api/fund/eqsfund", {}, TTL.m2, fresh),
  /** Phase 29 filings: FTS MA LEGAL BIO RELS ESG (`/api/filings/<fn>`, the client lives in filingsApi.ts). */
  filings: filingsApi.get,
  /** Phase 30 macro depth: MMR NOWC ECFC FOMC WB CRPR FWCV BTMM WCRS CDR CTM TSYS NRGF AGRI RE WPE (`/api/macrod/<fn>`). */
  macro: (fn: string, params: Params, fresh = false) => get<Envelope<TablePayload>>(`/api/macrod/${fn}`, params, TTL.m2, fresh),
  /** Phase 31 QRY (`/api/query?q=`): the same answer the SDK and the Excel bridge read. Short client cache: a query is cheap to repeat. */
  query: (q: string, fresh = false) => get<Envelope<TablePayload>>("/api/query", { q }, TTL.s30, fresh),
  /** Phase 31 FLD: the QRY field catalog searched by words. */
  fields: (q: string) => get<Envelope<TablePayload>>("/api/query/fields", { q }, TTL.m2),
  /** Non-US curves, credit spreads and auctions (RATES views). */
  rates: (fn: string, params: Params, fresh = false) => get<Envelope<TablePayload>>(`/api/rates/${fn}`, params, TTL.m1, fresh),
};
