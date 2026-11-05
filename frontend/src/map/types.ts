/** Shared types for the MAP panel. Pure: no DOM, no network (vitest imports this). */

/** Colour meaning. The canvas looks the names up in the theme's CSS variables (`--up`, `--warn`, ...), so a theme change recolours the map. */
export type Tone = "fg" | "dim" | "up" | "down" | "warn" | "err" | "acc" | "val";

/** [south, west, north, east] in degrees. */
export type Box = [number, number, number, number];

interface Base {
  /** Unique inside its layer. */
  id: string;
  /** Short text next to the shape on the map and in the detail list. */
  label: string;
  tone: Tone;
  /** Label / value pairs for the side detail list. */
  detail: [string, string][];
  /** When this observation was made, epoch seconds (the detail list shows its age). Absent when the source gives no time per item. */
  time?: number;
}

/** A dot. `r` is the radius in CSS pixels (size carries meaning, e.g. port activity). */
export interface PointShape extends Base {
  kind: "pt";
  lat: number;
  lon: number;
  r: number;
}

/** A polyline of [lon, lat] points (a storm's path). `lat`/`lon` = where the line "is" (its newest point) for jumps and the detail list. */
export interface LineShape extends Base {
  kind: "line";
  pts: [number, number][];
  lat: number;
  lon: number;
}

/** A labelled rectangle (a chokepoint box). `lat`/`lon` = its centre. */
export interface BoxShape extends Base {
  kind: "box";
  box: Box;
  lat: number;
  lon: number;
}

export type Shape = PointShape | LineShape | BoxShape;

/** What a layer's `load` returns. */
export interface LayerData {
  shapes: Shape[];
  /** Source label from the server's envelope. */
  source: string;
  /** Epoch seconds the server fetched the data (envelope `as_of`). */
  asOf: number;
  stale: boolean;
  /** Extra honest labelling (DOC-SHAPED fixture, wildfires left out, ...). Shown under the layer list. */
  notes: string[];
  /** True when the data is a test fixture / invented, so the layer says so on screen. */
  fixture?: boolean;
}
