/** Layer 2: the busiest ports (IMF PortWatch, satellite ship signals, weekly). Dot size = average port calls per day. */
import type { GeoPorts } from "../../net/types";
import { layerData, type MapLayer } from "../layer";
import type { LayerData, PointShape } from "../types";

/** Radius in pixels from calls per day: the square root keeps the biggest port (hundreds of calls) from hiding the rest. */
export function radius(callsPerDay: number): number {
  return Math.max(2, Math.min(12, 1.5 + Math.sqrt(Math.max(callsPerDay, 0)) * 0.55));
}

/** Pure: one dot per port. */
export function toShapes(p: GeoPorts): PointShape[] {
  return p.rows.map((r) => ({
    kind: "pt",
    id: r.id,
    label: r.name,
    tone: "fg",
    r: radius(r.calls_per_day),
    lat: r.lat,
    lon: r.lon,
    time: Date.parse(`${r.newest}T23:59:59Z`) / 1000, // the newest DAY on record; the age shown is from the end of that day
    detail: [
      ["PORT", r.name],
      ["COUNTRY", r.country ?? ""],
      ["CODE", r.locode ?? ""],
      ["CALLS PER DAY", `${r.calls_per_day.toFixed(1)} (7-DAY AVERAGE)`],
      ["RANK", `${r.rank} OF THE BUSIEST ${p.rows.length} LISTED`],
      ["DATA UP TO", r.newest],
    ],
  }));
}

export const ports: MapLayer = {
  id: "ports",
  name: "PORTS",
  key: "2",
  source: "IMF PORTWATCH (SATELLITE SHIP SIGNALS)",
  shapes: "DOTS",
  colour: "DOT SIZE = AVERAGE PORT CALLS PER DAY (7 DAYS); COLOUR IS NEUTRAL",
  refresh: "PUBLISHED WEEKLY; RECHECKED HOURLY",
  refreshMs: 3_600_000,
  async load({ api, fresh }): Promise<LayerData> {
    const env = await api.geoPorts(fresh);
    const d = env.data;
    const notes = [d.note];
    if (d.skipped > 0) notes.push(`${d.skipped} PORTS LEFT OUT: NO COORDINATES IN THE PORT LIST`);
    return layerData(env, toShapes(d), notes);
  },
};
