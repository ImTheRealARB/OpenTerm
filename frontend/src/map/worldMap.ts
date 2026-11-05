/**
 * The coastline and border outline: decoding and culling. Pure (no DOM).
 *
 * `worldData.json` is built by `scripts/build_world_map.mjs` from Natural Earth 1:50m (public domain, via the npm package world-atlas).
 * It holds "arcs": polylines stored as [x0, y0, dx, dy, dx, dy, ...] in hundredths of a degree (delta coding keeps the file small).
 * `coast` arcs belong to one country (a coastline); `border` arcs are shared by two (stored once, so nothing is drawn twice).
 */
import { nx, ny, type Bounds } from "./projection";

export interface Arc {
  /** lon, lat, lon, lat, ... in degrees. */
  pts: Float32Array;
  /** The same points as 0..1 world coordinates (x, y pairs, Mercator already applied), so drawing is plain multiply-and-add per point. */
  world: Float64Array;
  /** [west, south, east, north] of the arc, used to skip arcs that are off screen. */
  bbox: [number, number, number, number];
}

/** Builds one Arc (float arrays + bounding box) from a run of [lon, lat] points. */
function makeArc(lonlat: number[]): Arc {
  const pts = Float32Array.from(lonlat);
  const world = new Float64Array(lonlat.length);
  let w = Infinity;
  let s = Infinity;
  let e = -Infinity;
  let n = -Infinity;
  for (let i = 0; i < lonlat.length; i += 2) {
    const lon = lonlat[i];
    const lat = lonlat[i + 1];
    world[i] = nx(lon);
    world[i + 1] = ny(lat);
    if (lon < w) w = lon;
    if (lon > e) e = lon;
    if (lat < s) s = lat;
    if (lat > n) n = lat;
  }
  return { pts, world, bbox: [w, s, e, n] };
}

/**
 * Turns the delta-coded integer arcs into float arrays with bounding boxes. Runs once, when the panel first loads.
 * An arc that crosses the date line (Russia's far east, Fiji, Antarctica's coast) jumps from about +180 to -180 between two points;
 * drawn as it is, that jump would be a line straight across the whole map. So such an arc is cut in two at the jump.
 */
export function decodeArcs(raw: number[][], unit: number): Arc[] {
  const out: Arc[] = [];
  for (const a of raw) {
    let x = 0;
    let y = 0;
    let run: number[] = [];
    let prevLon = NaN;
    for (let i = 0; i < a.length; i += 2) {
      x += a[i];
      y += a[i + 1];
      const lon = x / unit;
      if (Math.abs(lon - prevLon) > 180) {
        if (run.length >= 4) out.push(makeArc(run));
        run = [];
      }
      run.push(lon, y / unit);
      prevLon = lon;
    }
    if (run.length >= 4) out.push(makeArc(run));
  }
  return out;
}

/** The arcs whose bounding box touches the view: the only ones worth drawing. */
export function arcsInBounds(arcs: Arc[], b: Bounds): Arc[] {
  // `b.s <= b.n` always holds after a view is built, but a caller passing a flipped box would otherwise get nothing; keep both orders honest.
  const s = Math.min(b.s, b.n);
  const n = Math.max(b.s, b.n);
  return arcs.filter((a) => a.bbox[2] >= b.w && a.bbox[0] <= b.e && a.bbox[3] >= s && a.bbox[1] <= n);
}
