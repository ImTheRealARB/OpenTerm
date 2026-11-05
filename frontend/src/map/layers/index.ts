/**
 * The layer registry. List order = the order in the side list = the number keys (the first layer is key 1). The panel DRAWS the list
 * bottom-up (the last layer first), so the first layer, vessels, ends up on top and is never hidden under a port dot or a box.
 * To add a layer: write `map/layers/<name>.ts` and add it here.
 */
import type { MapLayer } from "../layer";
import { chokepoints } from "./chokepoints";
import { events } from "./events";
import { ports } from "./ports";
import { quakes } from "./quakes";
import { vessels } from "./vessels";

export const LAYERS: MapLayer[] = [vessels, ports, chokepoints, quakes, events];

/** Layers shown ON when MAP is opened with no layer words: everything keyless. Vessels waits for a key, a listen and an area. */
export const DEFAULT_ON = ["chokepoints", "ports", "quakes", "events"];
