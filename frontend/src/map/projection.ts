/**
 * MAP projection: Web Mercator, the same maths every web map uses. Pure functions, no DOM.
 *
 * Why Mercator (and not equirectangular, where x = longitude and y = latitude): Mercator keeps SHAPES right at any zoom, so a strait
 * looks like the strait it is, and a ship's course on the screen is its real compass course. The cost is that the poles stretch;
 * latitude is cut at MAX_LAT (about 85 degrees), the same limit as every web map, and there is nothing to trade up there anyway.
 *
 * A view is {lon, lat, zoom}: the lon/lat in the CENTRE of the canvas, and a zoom level. At zoom z the whole world is
 * TILE * 2^z pixels wide and tall (z = 0: 256 px). Zoom is continuous, so +/- steps and the wheel can use any fraction.
 */

export const TILE = 256;
export const MAX_ZOOM = 12; // about 40 m per pixel: far deeper than the 1:50m coastline is accurate, so no use going further
export const MAX_LAT = 85.0511287798;

export interface View {
  lon: number;
  lat: number;
  zoom: number;
}
export interface Size {
  w: number;
  h: number;
}
export interface Bounds {
  w: number;
  s: number;
  e: number;
  n: number;
}

export const worldPx = (zoom: number) => TILE * 2 ** zoom;

/** Longitude to 0..1 across the world (west edge = 0). */
export const nx = (lon: number) => (lon + 180) / 360;

/** Latitude to 0..1 down the world (north edge = 0), Mercator-stretched. Latitudes beyond MAX_LAT are clamped, never Infinity. */
export function ny(lat: number): number {
  const phi = (Math.max(-MAX_LAT, Math.min(MAX_LAT, lat)) * Math.PI) / 180;
  return 0.5 - Math.log(Math.tan(Math.PI / 4 + phi / 2)) / (2 * Math.PI);
}

const lonOf = (x: number) => x * 360 - 180;
const latOf = (y: number) => (Math.atan(Math.sinh(Math.PI * (1 - 2 * y))) * 180) / Math.PI;

/** Lowest zoom allowed: the world just covers the canvas (so there is never empty space around it). */
export function minZoom(size: Size): number {
  return Math.log2(Math.max(size.w, size.h, 1) / TILE);
}

/** lon/lat to canvas pixels (CSS pixels, origin top-left). */
export function project(view: View, size: Size, lon: number, lat: number): [number, number] {
  const W = worldPx(view.zoom);
  return [(nx(lon) - nx(view.lon)) * W + size.w / 2, (ny(lat) - ny(view.lat)) * W + size.h / 2];
}

/** Canvas pixels to lon/lat. */
export function unproject(view: View, size: Size, sx: number, sy: number): [number, number] {
  const W = worldPx(view.zoom);
  return [lonOf(nx(view.lon) + (sx - size.w / 2) / W), latOf(ny(view.lat) + (sy - size.h / 2) / W)];
}

/** Keeps the zoom in range and the canvas inside the world (no empty bands past the poles or the date line). */
export function clampView(view: View, size: Size): View {
  const zoom = Math.max(minZoom(size), Math.min(MAX_ZOOM, view.zoom));
  const W = worldPx(zoom);
  const clampAxis = (c: number, half: number) => (half * 2 >= W ? 0.5 : Math.max(half / W, Math.min(1 - half / W, c)));
  const cx = clampAxis(nx(Math.max(-180, Math.min(180, view.lon))), size.w / 2);
  const cy = clampAxis(ny(view.lat), size.h / 2);
  return { lon: lonOf(cx), lat: latOf(cy), zoom };
}

/** Drags the map by (dx, dy) pixels: the map follows the pointer, so dragging right shows what lies west. */
export function panBy(view: View, size: Size, dx: number, dy: number): View {
  const W = worldPx(view.zoom);
  return clampView({ lon: lonOf(nx(view.lon) - dx / W), lat: latOf(ny(view.lat) - dy / W), zoom: view.zoom }, size);
}

/** Changes zoom by `dz` levels while the lon/lat under pixel (sx, sy) stays under it (wheel zoom at the cursor; the canvas centre for keys). */
export function zoomAt(view: View, size: Size, sx: number, sy: number, dz: number): View {
  const [lon, lat] = unproject(view, size, sx, sy);
  const zoom = Math.max(minZoom(size), Math.min(MAX_ZOOM, view.zoom + dz));
  const W = worldPx(zoom);
  return clampView({ lon: lonOf(nx(lon) - (sx - size.w / 2) / W), lat: latOf(ny(lat) - (sy - size.h / 2) / W), zoom }, size);
}

/** The view that shows `box` ([south, west, north, east]) as large as possible with `pad` pixels of margin. */
export function fitBox(box: [number, number, number, number], size: Size, pad: number): View {
  const [s, w, n, e] = box;
  const dx = Math.max(nx(e) - nx(w), 1e-9);
  const dy = Math.max(ny(s) - ny(n), 1e-9);
  const px = Math.min(Math.max(size.w - 2 * pad, 1) / dx, Math.max(size.h - 2 * pad, 1) / dy);
  return clampView({ lon: lonOf((nx(w) + nx(e)) / 2), lat: latOf((ny(s) + ny(n)) / 2), zoom: Math.log2(px / TILE) }, size);
}

/** lon/lat of the canvas edges (used to skip everything off screen). */
export function viewBounds(view: View, size: Size): Bounds {
  const [w, n] = unproject(view, size, 0, 0);
  const [e, s] = unproject(view, size, size.w, size.h);
  return { w, s, e, n };
}
