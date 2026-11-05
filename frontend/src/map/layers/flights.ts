/**
 * Layer 6: aircraft over one city box, from the OpenSky Network (FLT's data: ADS-B positions reported by aircraft transponders and
 * collected by volunteer receivers, so coverage is partial). Free; an OpenSky account in APIKEYS only raises the daily credits.
 *
 * Like vessels it loads ONE area at a time (a small city box, because OpenSky charges credits by box size and the anonymous limit is
 * 400 a day). Unlike vessels the areas are FLT's city presets, so the area is the preset whose centre is nearest the map's centre cross.
 */
import { fmtAge, fmtDegrees, fmtKnots, fmtLatLon } from "../../functions/aisArgs";
import { FLT_AREAS } from "../../functions/fltArgs";
import type { FltPayload } from "../../net/api";
import { layerData, type MapLayer } from "../layer";
import type { Box, LayerData, PointShape } from "../types";
import { inBox } from "./vessels";

/**
 * The FLT presets as [south, west, north, east]. This is a COPY of `PRESETS` in backend/openterm/world/flights.py (the server owns the
 * boxes; the map needs them only to pick the nearest one). A pytest in test_map_layers.py fails if the two lists drift apart.
 */
export const FLT_BOXES: Record<string, Box> = {
  LONDON: [51.3, -0.6, 51.7, 0.2],
  NYC: [40.5, -74.3, 41.0, -73.6],
  DUBAI: [24.9, 54.9, 25.5, 55.7],
  SINGAPORE: [1.1, 103.5, 1.6, 104.2],
  MUMBAI: [18.8, 72.6, 19.3, 73.2],
  BENGALURU: [12.7, 77.3, 13.3, 77.9],
  FRANKFURT: [49.8, 8.2, 50.3, 9.0],
};

/** The preset city whose box centre is nearest (lat, lon). Plain degrees distance is enough: it only ranks a handful of far-apart cities. */
export function nearestFltArea(lat: number, lon: number): string | null {
  let best: string | null = null;
  let bestD = Infinity;
  for (const name of FLT_AREAS) {
    const b = FLT_BOXES[name];
    if (!b) continue;
    const dLat = (b[0] + b[2]) / 2 - lat;
    const dLon = (b[1] + b[3]) / 2 - lon;
    const d = dLat * dLat + dLon * dLon;
    if (d < bestD) {
      bestD = d;
      best = name;
    }
  }
  return best;
}

/** Pure: one dot per aircraft with a position inside the box that was asked for (the replay fixture ignores the box, like AIS's). */
export function toShapes(p: FltPayload, area: string): PointShape[] {
  const box = p.box;
  return p.rows
    .filter((r) => (box ? inBox(box, r.lat, r.lon) : true))
    .map((r) => ({
      kind: "pt" as const,
      id: `${area}:${r.icao24}`,
      label: r.callsign || r.icao24.toUpperCase(),
      // On the ground = dim; in the air = the "moving" colour. Colour never says anything about safety or altitude.
      tone: r.on_ground ? ("dim" as const) : ("acc" as const),
      r: 3,
      lat: r.lat,
      lon: r.lon,
      ...(r.seen != null ? { time: r.seen } : {}),
      detail: [
        ["CALLSIGN", r.callsign || "(NONE)"],
        ["ICAO24", r.icao24.toUpperCase()],
        // Country is where the aircraft is REGISTERED, not where it flies (the server says so too).
        ["REGISTERED IN", r.country || "UNKNOWN"],
        ["ALTITUDE", r.on_ground ? "ON THE GROUND" : r.alt_ft == null ? "NOT REPORTED" : `${Math.round(r.alt_ft).toLocaleString("en-US")} FT`],
        ["SPEED", r.speed_kt == null ? "NOT REPORTED" : `${fmtKnots(r.speed_kt)} KN`],
        ["HEADING", r.heading == null ? "NOT REPORTED" : `${fmtDegrees(r.heading)} DEG`],
        ["POSITION", fmtLatLon(r.lat, r.lon)],
        ["REPORT AGE", r.age_s == null ? "NOT REPORTED" : fmtAge(r.age_s)],
        ["AREA", area],
      ] as [string, string][],
    }));
}

export const flights: MapLayer = {
  id: "flights",
  name: "FLIGHTS",
  key: "6",
  source: "OPENSKY NETWORK (ADS-B TRANSPONDER REPORTS, PARTIAL COVERAGE)",
  shapes: "DOTS",
  colour: "AMBER-BLUE = IN THE AIR, DIM = ON THE GROUND",
  refresh: "LOADS THE CITY NEAREST THE CENTRE CROSS; A ADDS ANOTHER CITY; F5 RELOADS (EACH LOAD COSTS OPENSKY CREDITS)",
  refreshMs: 0,
  perArea: true,
  loadKey: "A",
  loadLabel: "AIRCRAFT",
  nearestArea: nearestFltArea,
  async load({ api, fresh, area }): Promise<LayerData> {
    if (!area) throw new Error("FLIGHTS NEEDS A CITY");
    const env = await api.flt(area, fresh);
    const d = env.data;
    const notes = [d.note, d.access];
    if (d.fixture) notes.unshift("DOC-SHAPED TEST DATA: INVENTED AIRCRAFT IN THE DOCUMENTED RESPONSE SHAPE, NOT REAL TRAFFIC");
    if (d.rows.length === 0) notes.push(`${area}: NO AIRCRAFT REPORTED: PARTIAL RECEIVER COVERAGE, NOT PROOF THE SKY IS EMPTY`);
    if (d.truncated > 0) notes.push(`${area}: ${d.truncated} MORE AIRCRAFT LEFT OFF (SHOWING ${d.rows.length})`);
    return layerData(env, toShapes(d, area), notes, d.fixture);
  },
};
