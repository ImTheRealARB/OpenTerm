/**
 * What a MAP layer is. Adding a layer = one file in `map/layers/` that exports a `MapLayer`, plus one line in `map/layers/index.ts`.
 * The panel does everything else (toggle, list, loading / error / stale labels, drawing, picking, details).
 *
 * Layer files import only TYPES from net/types and net/worldApi (`import type`), and get the API object through `LoadCtx`, so vitest can run
 * their pure `toShapes` conversion without a browser.
 */
import type { Envelope } from "../net/types";
import type { worldApi } from "../net/worldApi";
import type { LayerData, Shape } from "./types";

export interface LoadCtx {
  api: typeof worldApi;
  /** Skip the client cache (F5). */
  fresh: boolean;
  /** For layers that cover one area at a time (vessels: a chokepoint name). Null for the others. */
  area: string | null;
}

export interface MapLayer {
  /** Lower-case id used in `MAP <layer>` aliases and as the key of the layer's state. */
  id: string;
  name: string;
  /** Number key that toggles the layer (1 to 9). */
  key: string;
  /** The data source in a few words (the exact source label also comes with every answer). */
  source: string;
  /** What the shapes are: "dots", "dots and paths", "rectangles". */
  shapes: string;
  /** What colour and size mean on the map. */
  colour: string;
  /** The refresh rule in words, and the same as milliseconds (0 = only when asked: F5). */
  refresh: string;
  refreshMs: number;
  /** The env key name this layer needs, when it needs one. A missing key is shown on this layer only. */
  needsKey?: string;
  /** True when the layer loads one named area at a time (vessels), and which key loads another area. */
  perArea?: boolean;
  /** For perArea layers: the panel key that loads another area ("V" for vessels, "A" for flights) and what it listens for in the status line. */
  loadKey?: string;
  loadLabel?: string;
  /** For perArea layers whose areas are a fixed list (flights): the area nearest this map centre. Without it the panel uses the chokepoint boxes (vessels). */
  nearestArea?(lat: number, lon: number): string | null;
  load(ctx: LoadCtx): Promise<LayerData>;
}

/** The layer data every `load` builds from a server envelope. */
export function layerData(env: Envelope<unknown>, shapes: Shape[], notes: string[], fixture = false): LayerData {
  return { shapes, source: env.source ?? "", asOf: env.as_of, stale: env.stale, notes, fixture };
}
