/** Layer 1: ships that reported a position inside a chokepoint box during one ~8 s listen (AISstream, free key AISSTREAM_API_KEY). */
import { fmtAge, fmtDegrees, fmtKnots, fmtLatLon } from "../../functions/aisArgs";
import type { AisPayload } from "../../net/types";
import { layerData, type MapLayer } from "../layer";
import type { LayerData, PointShape } from "../types";

// A ship that reports it is not under control or aground is the one thing worth colouring loudly.
const TROUBLE = new Set(["NOT UNDER COMMAND", "AGROUND"]);
const MOVING_KN = 0.5; // below this a ship is treated as not moving (GPS noise on a moored ship reads 0.1 to 0.3)

/** True when a position lies inside the box [south, west, north, east] (edges included). */
export function inBox(box: [number, number, number, number], lat: number, lon: number): boolean {
  return lat >= box[0] && lon >= box[1] && lat <= box[2] && lon <= box[3];
}

/**
 * Pure: one dot per ship that is inside the box that was asked for. A real AISstream listen only reports ships inside its box, so
 * nothing is dropped there; the recorded test replay returns the same ships for every box, and those must not be drawn in a box
 * they are not in (the layer counts them and says so).
 */
export function toShapes(p: AisPayload): PointShape[] {
  return p.rows.filter((r) => inBox(p.box, r.lat, r.lon)).map((r) => {
    const trouble = TROUBLE.has(r.nav_name);
    const moving = r.sog != null && r.sog >= MOVING_KN;
    return {
      kind: "pt",
      id: `${p.area}:${r.mmsi}`,
      label: r.name || `MMSI ${r.mmsi}`,
      // A ship remembered from an EARLIER listen is drawn dim: its position may be minutes old. Trouble stays loud even when remembered,
      // because hiding a grounded ship is worse than showing a stale dot (its detail line says how old the position is).
      tone: trouble ? "warn" : r.remembered ? "dim" : moving ? "acc" : "dim",
      r: 3,
      lat: r.lat,
      lon: r.lon,
      time: r.seen,
      detail: [
        ["NAME", r.name || "(NO NAME)"],
        ["MMSI", String(r.mmsi)],
        ["TYPE", r.type],
        ["SPEED", r.sog == null ? "NOT REPORTED" : `${fmtKnots(r.sog)} KN`],
        ["COURSE", r.cog == null ? "NOT REPORTED" : `${fmtDegrees(r.cog)} DEG`],
        ["STATUS", r.nav_name],
        // Destination and ETA are typed by the crew; say so, and how old the record is.
        ["DESTINATION", r.dest ? `${r.dest} (TYPED BY CREW${r.static_age_s != null ? `, ${fmtAge(r.static_age_s)} OLD` : ""})` : "NONE RECEIVED YET"],
        ["ETA UTC", r.eta ?? ""],
        ["POSITION", fmtLatLon(r.lat, r.lon)],
        ["POSITION AGE", `${fmtAge(r.age_s)} (${r.remembered ? "MEMORY, FROM AN EARLIER LISTEN" : "HEARD THIS LISTEN"})`],
        ["AREA", p.area],
      ],
    };
  });
}

export const vessels: MapLayer = {
  id: "vessels",
  name: "VESSELS",
  key: "1",
  source: "AISSTREAM (LIVE SHIP POSITIONS)",
  shapes: "DOTS",
  colour: "AMBER-BLUE = UNDER WAY, DIM = STOPPED OR REMEMBERED FROM AN EARLIER LISTEN, YELLOW = NOT UNDER COMMAND OR AGROUND",
  refresh: "LISTENS ~8 S PER AREA; F5 LISTENS AGAIN; V ADDS THE AREA NEAR THE CENTRE",
  refreshMs: 0,
  needsKey: "AISSTREAM_API_KEY",
  perArea: true,
  loadKey: "V",
  loadLabel: "SHIPS",
  async load({ api, fresh, area }): Promise<LayerData> {
    if (!area) throw new Error("VESSELS NEEDS AN AREA");
    const env = await api.ais(area, fresh);
    const d = env.data;
    const notes = [d.note];
    const outside = d.rows.filter((r) => !inBox(d.box, r.lat, r.lon)).length;
    if (outside > 0) notes.push(`${area}: ${outside} POSITIONS OUTSIDE THE BOX LEFT OFF THE MAP (THE TEST REPLAY RETURNS THE SAME SHIPS FOR EVERY BOX)`);
    if (d.fixture) notes.unshift("DOC-SHAPED TEST DATA: INVENTED SHIPS IN THE DOCUMENTED MESSAGE SHAPE, NOT REAL TRAFFIC");
    if (d.rows.length === outside) notes.push(`${area}: NO POSITION REPORTS IN ${d.listened_s.toFixed(0)} S: A QUIET AREA OR A SLOW FEED, NOT PROOF THE AREA IS EMPTY`);
    if (d.remembered > 0) notes.push(`${area}: ${d.remembered} SHIPS FROM MEMORY (UP TO ${Math.round(d.memory_s / 60)} MIN OLD), DRAWN DIM`);
    if (d.truncated > 0) notes.push(`${area}: ${d.truncated} OLDER SHIPS LEFT OUT (SHOWING THE NEWEST ${d.rows.length})`);
    return layerData(env, toShapes(d), notes, d.fixture);
  },
};
