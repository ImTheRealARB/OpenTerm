/** Layer 3: the eight chokepoint boxes AIS listens to, drawn as rectangles. Select one and press V to load the ships inside it. */
import type { GeoChokepoints } from "../../net/types";
import { layerData, type MapLayer } from "../layer";
import type { BoxShape, LayerData } from "../types";

/** Pure: one rectangle per preset box. */
export function toShapes(p: GeoChokepoints): BoxShape[] {
  return p.rows.map((r) => ({
    kind: "box",
    id: r.id,
    label: r.name,
    tone: "dim",
    box: r.box,
    lat: r.lat,
    lon: r.lon,
    detail: [
      ["CHOKEPOINT", r.name],
      ["BOX S W N E", r.box.map((v) => v.toFixed(2)).join(" ")],
      ["SHIPS", "PRESS V TO LISTEN FOR SHIPS INSIDE THIS BOX"],
    ],
  }));
}

export const chokepoints: MapLayer = {
  id: "chokepoints",
  name: "CHOKEPOINTS",
  key: "3",
  source: "OPENTERM PRESETS (BOXES DRAWN BY EYE)",
  shapes: "RECTANGLES",
  colour: "DIM = A PLACE, NOT A MEASUREMENT",
  refresh: "STATIC",
  refreshMs: 0,
  async load({ api, fresh }): Promise<LayerData> {
    const env = await api.geoChokepoints(fresh);
    return layerData(env, toShapes(env.data), [env.data.note]);
  },
};
