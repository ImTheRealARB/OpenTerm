/** What the GP chart adds on top of price bars: tick-built bars (GIP), earnings / dividend / split markers, and saved drawings. */
import { get, send, TTL } from "./core";
import type { ChartEvents, Envelope, TickBars } from "./types";

export const chartApi = {
  ticks: (symbol: string, bar: string) => get<Envelope<TickBars>>(`/api/world/ticks/${encodeURIComponent(symbol)}`, { bar }, 0),
  /** GP `EVT`: earnings (last four reported), ex-dividend dates and splits. */
  events: (symbol: string, fresh = false) => get<Envelope<ChartEvents>>("/api/world/events", { symbol }, TTL.m2, fresh),
  drawings: (symbol: string) => send<{ symbol: string; drawings: unknown[]; updated_at: number | null }>("GET", `/api/drawings/${encodeURIComponent(symbol)}`),
  saveDrawings: (symbol: string, drawings: unknown[]) =>
    send<{ symbol: string; drawings: unknown[]; updated_at: number }>("PUT", `/api/drawings/${encodeURIComponent(symbol)}`, { drawings }),
};
