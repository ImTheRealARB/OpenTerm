/** Layer 5: open natural events from NASA EONET (storms, volcanoes, floods, sea ice...), wildfires left out. Storms also draw their path. */
import { fmtAge } from "../../functions/aisArgs";
import type { GeoEvents } from "../../net/api";
import { layerData, type MapLayer } from "../layer";
import type { LayerData, Shape, Tone } from "../types";

// Colour is the KIND of event (a legend, not a score): storms yellow, volcanoes red, floods blue-green (up), ice dim, the rest plain.
const TONES: Record<string, Tone> = { severeStorms: "warn", volcanoes: "err", floods: "up", seaLakeIce: "dim", dustHaze: "dim" };
export const toneOf = (category: string): Tone => TONES[category] ?? "fg";

/** Pure: a dot at each event's newest position, plus a line for the earlier positions of an event that has moved. */
export function toShapes(p: GeoEvents): Shape[] {
  const out: Shape[] = [];
  for (const e of p.rows) {
    const tone = toneOf(e.category);
    out.push({
      kind: "pt",
      id: e.id,
      label: e.title,
      tone,
      r: 4,
      lat: e.lat,
      lon: e.lon,
      time: e.time,
      detail: [
        ["EVENT", e.title],
        ["KIND", e.category_title],
        ["REPORTED BY", e.source ?? ""],
        ["INTENSITY", e.mag == null ? "" : `${e.mag} ${e.mag_unit ?? ""}`.trim()],
        ["PATH POINTS", String(e.track.length)],
        ["PAGE", e.url ?? ""],
      ],
    });
    if (e.track.length > 1) {
      out.push({ kind: "line", id: `${e.id}:path`, label: `${e.title} (PATH)`, tone, pts: e.track, lat: e.lat, lon: e.lon, time: e.time,
        detail: [["EVENT", e.title], ["PATH", `${e.track.length} REPORTED POSITIONS, OLDEST FIRST`]] });
    }
  }
  return out;
}

export const events: MapLayer = {
  id: "events",
  name: "EVENTS",
  key: "5",
  source: "NASA EONET (OPEN EVENTS, NO WILDFIRES)",
  shapes: "DOTS AND PATHS",
  colour: "KIND OF EVENT: YELLOW = STORM, RED = VOLCANO, GREEN = FLOOD, DIM = ICE OR DUST, AMBER = OTHER",
  refresh: "EVERY 10 MIN",
  refreshMs: 600_000,
  async load({ api, fresh }): Promise<LayerData> {
    const env = await api.geoEvents(fresh);
    const d = env.data;
    const newest = d.rows[0];
    const notes = [d.note, newest ? `NEWEST REPORT ${fmtAge(Date.now() / 1000 - newest.time)} AGO` : "NO OPEN EVENTS"];
    if (d.skipped > 0) notes.push(`${d.skipped} EVENTS LEFT OUT: NO POINT POSITION (AREAS ARE NOT DRAWN YET)`);
    return layerData(env, toShapes(d), notes);
  },
};
