/** World data panels (one method per panel): macro boards, energy, shipping, weather, prediction markets, crypto depth, funds, US government, UK / address lookups, ships, flights and the MAP layers. */
import { get, TTL } from "./core";
import type {
  AddrPayload, AisPayload, CdepPayload, CenbPayload, CongressPayload, DbsPayload, DefiPayload, Envelope, FecPayload,
  FedregPayload, FigiResult, FltPayload, FundPayload, GeoChokepoints, GeoEvents, GeoPorts, GeoQuakes, HolidayCalendar,
  LiqPayload, MfNavPayload, MfPayload, NrgPayload, PortsPayload, PredDetail, PredPayload, ShipPayload, StblPayload,
  TradePayload, UkcoPayload, UsaspPayload, UsMacroPayload, WecoPayload, WetrPayload, WorldSeries,
} from "./types";

export const worldApi = {
  mf: (q: string, fresh = false) => get<Envelope<MfPayload>>("/api/world/mf", { q }, TTL.m10, fresh),
  trade: (reporter: string, partner: string, hs: string, years: number, fresh = false) =>
    get<Envelope<TradePayload>>("/api/world/trade", { reporter, partner, hs, years: String(years) }, TTL.m10, fresh),
  usmac: (src: string, q: string, years: number, fresh = false) =>
    get<Envelope<UsMacroPayload>>("/api/world/usmac", { src, q, years: String(years) }, TTL.m10, fresh),
  stats: (country: string, ind: string, fresh = false) => get<Envelope<WorldSeries>>("/api/world/stats", { country, ind }, TTL.m10, fresh),
  dbsearch: (q: string, dataset: string, offset: number, fresh = false) =>
    get<Envelope<DbsPayload>>("/api/world/dbsearch", { q, dataset, offset: String(offset) }, TTL.m10, fresh),
  weco: (fresh = false) => get<Envelope<WecoPayload>>("/api/world/weco", undefined, TTL.m10, fresh),
  cenb: (fresh = false) => get<Envelope<CenbPayload>>("/api/world/cenb", undefined, TTL.m5, fresh),
  nrg: (fresh = false) => get<Envelope<NrgPayload>>("/api/world/nrg", undefined, TTL.m5, fresh),
  ship: (fresh = false) => get<Envelope<ShipPayload>>("/api/world/ship", undefined, TTL.m5, fresh),
  ports: (q: string, fresh = false) => get<Envelope<PortsPayload>>("/api/world/ports", { q }, TTL.m5, fresh),
  wetr: (place: string, fresh = false) => get<Envelope<WetrPayload>>("/api/world/wetr", { place }, TTL.m5, fresh),
  holidays: (mkt: string, year: number) => get<Envelope<HolidayCalendar>>("/api/world/holidays", { mkt, year: String(year) }, TTL.h1),
  pred: (q: string, fresh = false) => get<Envelope<PredPayload>>("/api/world/pred", { q }, TTL.m1, fresh),
  predDetail: (source: string, id: string, fresh = false) => get<Envelope<PredDetail>>("/api/world/pred/detail", { source, id }, TTL.m1, fresh),
  cdep: (pair: string, fresh = false) => get<Envelope<CdepPayload>>("/api/world/cdep", { pair }, TTL.s4, fresh),
  fund: (sym: string, fresh = false) => get<Envelope<FundPayload>>("/api/world/fund", { sym }, TTL.s30, fresh),
  liq: (sym: string, fresh = false) => get<Envelope<LiqPayload>>("/api/world/liq", { sym }, TTL.s20, fresh),
  stbl: (chain: string, fresh = false) => get<Envelope<StblPayload>>("/api/world/stbl", { chain }, TTL.m10, fresh),
  defi: (q: string, fresh = false) => get<Envelope<DefiPayload>>("/api/world/defi", { q }, TTL.m10, fresh),
  mfnav: (q: string, fresh = false) => get<Envelope<MfNavPayload>>("/api/world/mfnav", { q }, TTL.h1, fresh),
  figi: (q: string, fresh = false) => get<Envelope<FigiResult>>("/api/world/figi", { q }, TTL.m10, fresh),
  ukco: (q: string, fresh = false) => get<Envelope<UkcoPayload>>("/api/world/ukco", { q }, TTL.m5, fresh),
  usasp: (q: string, fresh = false) => get<Envelope<UsaspPayload>>("/api/world/usasp", { q }, TTL.m5, fresh),
  fedreg: (q: string, fresh = false) => get<Envelope<FedregPayload>>("/api/world/fedreg", { q }, TTL.m2, fresh),
  fec: (q: string, fresh = false) => get<Envelope<FecPayload>>("/api/world/fec", { q }, TTL.m5, fresh),
  congress: (q: string, fresh = false) => get<Envelope<CongressPayload>>("/api/world/congress", { q }, TTL.m3, fresh),
  addr: (q: string, fresh = false) => get<Envelope<AddrPayload>>("/api/world/addr", { q }, TTL.s15, fresh),
  /** One listen takes about 8 s on the server (cached 20 s there); the client cache is short so F5 really listens again. */
  flt: (q: string, fresh = false) => get<Envelope<FltPayload>>("/api/world/flt", { q }, TTL.s30, fresh),
  ais: (q: string, fresh = false) => get<Envelope<AisPayload>>("/api/world/ais", { q }, TTL.s15, fresh),
  /** MAP layers. Each has its own server cache (USGS 2 min, EONET 10 min, PortWatch 6 h), so the client cache stays short. */
  geoQuakes: (fresh = false) => get<Envelope<GeoQuakes>>("/api/world/geo/quakes", undefined, TTL.s30, fresh),
  geoEvents: (fresh = false) => get<Envelope<GeoEvents>>("/api/world/geo/events", undefined, TTL.s30, fresh),
  geoPorts: (fresh = false) => get<Envelope<GeoPorts>>("/api/world/geo/ports", undefined, TTL.m1, fresh),
  geoChokepoints: (fresh = false) => get<Envelope<GeoChokepoints>>("/api/world/geo/chokepoints", undefined, TTL.m10, fresh),
};
