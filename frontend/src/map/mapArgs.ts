/** MAP: argument parsing (pure). `MAP`, `MAP VESSELS`, `MAP VESSELS HORMUZ`, `MAP PORTS QUAKES`, `MAP SUEZ`. */
import { AIS_AREAS } from "../functions/aisArgs";

/** Layer ids (see `map/layers/index.ts`) by the words a user may type. */
const ALIASES: Record<string, string> = {
  VESSELS: "vessels", SHIPS: "vessels", AIS: "vessels",
  PORTS: "ports",
  CHOKEPOINTS: "chokepoints", CHOKE: "chokepoints", STRAITS: "chokepoints",
  QUAKES: "quakes", EQ: "quakes", EARTHQUAKES: "quakes",
  EVENTS: "events", EONET: "events", NATURAL: "events",
};

export const MAP_USAGE = `MAP [VESSELS|PORTS|CHOKEPOINTS|QUAKES|EVENTS] [${AIS_AREAS.join("|")}]`;

export interface MapArgs {
  /** Layer ids to switch ON (in the order typed), or null = the default set. */
  layers: string[] | null;
  /** A chokepoint to centre on (and, with VESSELS, to load ships for). */
  area: string | null;
  error: string | null;
}

export function parseMapArgs(args: string[]): MapArgs {
  const layers: string[] = [];
  let area: string | null = null;
  for (const raw of args.join(" ").toUpperCase().split(/\s+/).filter(Boolean)) {
    if (ALIASES[raw]) {
      if (!layers.includes(ALIASES[raw])) layers.push(ALIASES[raw]);
    } else if ((AIS_AREAS as readonly string[]).includes(raw)) {
      if (area && area !== raw) return { layers: null, area: null, error: `USAGE: ${MAP_USAGE} (ONE AREA AT A TIME: ${area} AND ${raw})` };
      area = raw;
    } else {
      return { layers: null, area: null, error: `USAGE: ${MAP_USAGE} (UNKNOWN WORD ${raw})` };
    }
  }
  return { layers: layers.length ? layers : null, area, error: null };
}
