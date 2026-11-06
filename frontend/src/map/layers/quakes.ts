/** Layer 4: earthquakes of magnitude 4.5 and above in the past 7 days (USGS, keyless). */
import { fmtAge } from "../../functions/aisArgs";
import type { GeoQuakes } from "../../net/types";
import { layerData, type MapLayer } from "../layer";
import type { LayerData, PointShape, Tone } from "../types";

/** Radius from magnitude: each whole magnitude is ~32x the energy, so the dot grows by a clear step per unit. */
export function radius(mag: number | null): number {
  return mag == null ? 3 : Math.max(2.5, Math.min(14, 2.5 + (mag - 4.5) * 3));
}

/** Colour is severity: M7+ red, M6 to 7 yellow, below that the plain accent. */
export function tone(mag: number | null): Tone {
  return mag != null && mag >= 7 ? "err" : mag != null && mag >= 6 ? "warn" : "acc";
}

/** Pure: one dot per quake, newest first (the server sorts). */
export function toShapes(p: GeoQuakes): PointShape[] {
  return p.rows.map((q) => ({
    kind: "pt",
    id: q.id,
    label: `M${q.mag == null ? "?" : q.mag.toFixed(1)} ${q.place}`,
    tone: tone(q.mag),
    r: radius(q.mag),
    lat: q.lat,
    lon: q.lon,
    time: q.time,
    detail: [
      ["PLACE", q.place],
      ["MAGNITUDE", q.mag == null ? "" : `${q.mag.toFixed(1)}${q.mag_type ? ` ${q.mag_type.toUpperCase()}` : ""}`],
      ["DEPTH", q.depth_km == null ? "" : `${q.depth_km.toFixed(0)} KM`],
      ["OCCURRED", new Date(q.time * 1000).toISOString().replace("T", " ").slice(0, 16) + " UTC"],
      ["REVIEW", q.status ?? ""],
      ...(q.tsunami ? ([["TSUNAMI", "FLAG SET BY USGS (SEE THE EVENT PAGE)"]] as [string, string][]) : []),
      ...(q.alert ? ([["PAGER ALERT", q.alert.toUpperCase()]] as [string, string][]) : []),
    ],
  }));
}

export const quakes: MapLayer = {
  id: "quakes",
  name: "QUAKES",
  key: "4",
  source: "USGS (M4.5+, PAST 7 DAYS)",
  shapes: "DOTS",
  colour: "SIZE = MAGNITUDE; BLUE = UNDER M6, YELLOW = M6 TO 7, RED = M7+",
  refresh: "EVERY 2 MIN (FEED REBUILDS EVERY MINUTE)",
  refreshMs: 120_000,
  async load({ api, fresh }): Promise<LayerData> {
    const env = await api.geoQuakes(fresh);
    const d = env.data;
    const newest = d.rows[0];
    const notes = [d.note, newest ? `NEWEST QUAKE ${fmtAge(Date.now() / 1000 - newest.time)} AGO` : "NO QUAKES OF M4.5 OR MORE IN THE WINDOW"];
    if (d.skipped > 0) notes.push(`${d.skipped} QUAKES LEFT OUT: NO USABLE POSITION OR TIME`);
    return layerData(env, toShapes(d), notes);
  },
};
