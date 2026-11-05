// Builds frontend/src/map/worldData.json, the coastline + border outline the MAP panel draws.
//
// Source: Natural Earth 1:50m "Admin 0 - Countries" (public domain), through the npm package `world-atlas@2.0.2`
// (ISC licence, a pre-built TopoJSON of the Natural Earth files). Both are listed in THIRD_PARTY.md.
//
// Why TopoJSON arcs: each border between two countries is stored ONCE as a shared "arc", while a coastline arc belongs
// to exactly one country. Counting how many countries use an arc tells coast (1) from border (2+), and nothing is drawn twice.
//
// What this script does to the arcs: decode to degrees, drop Antarctica (no use for a market map, and Mercator blows it up),
// simplify each arc with Douglas-Peucker (TOLERANCE degrees), then store integers in 0.01 degree units as
// [startX, startY, dx, dy, dx, dy, ...] (delta coding keeps the numbers small, so the JSON and its gzip stay small).
//
// Run (only to refresh the data; the output is committed):  node scripts/build_world_map.mjs [tolerance_deg]
import { writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const SRC = "https://cdn.jsdelivr.net/npm/world-atlas@2.0.2/countries-50m.json";
const TOLERANCE = Number(process.argv[2] ?? 0.02); // degrees; 0.02 is about 2 km, below a pixel until you zoom to a strait
const UNIT = 100; // stored integers are hundredths of a degree
const OUT = join(dirname(fileURLToPath(import.meta.url)), "..", "frontend", "src", "map", "worldData.json");

const topo = await (await fetch(SRC)).json();
const { scale, translate } = topo.transform;

// Decode every arc to absolute [lon, lat] points (TopoJSON stores quantized deltas).
const arcs = topo.arcs.map((arc) => {
  let x = 0;
  let y = 0;
  return arc.map(([dx, dy]) => {
    x += dx;
    y += dy;
    return [x * scale[0] + translate[0], y * scale[1] + translate[1]];
  });
});

// How many countries use each arc. Antarctica (id "010") is skipped.
const uses = new Map();
const touch = (idx, id) => {
  const a = idx < 0 ? ~idx : idx;
  if (!uses.has(a)) uses.set(a, new Set());
  uses.get(a).add(id);
};
const walk = (n, id) => (Array.isArray(n) ? n.forEach((c) => walk(c, id)) : touch(n, id));
for (const g of topo.objects.countries.geometries) {
  if (g.id === "010") continue;
  walk(g.arcs, g.id ?? g.properties?.name);
}

// Douglas-Peucker: keep a point only if dropping it would move the line by more than `tol` degrees.
function simplify(pts, tol) {
  if (pts.length < 3) return pts;
  const keep = new Uint8Array(pts.length);
  keep[0] = keep[pts.length - 1] = 1;
  const stack = [[0, pts.length - 1]];
  while (stack.length) {
    const [a, b] = stack.pop();
    let worst = -1;
    let at = -1;
    const [ax, ay] = pts[a];
    const [bx, by] = pts[b];
    const dx = bx - ax;
    const dy = by - ay;
    const len2 = dx * dx + dy * dy;
    for (let i = a + 1; i < b; i++) {
      const [px, py] = pts[i];
      let d;
      if (len2 === 0) d = Math.hypot(px - ax, py - ay);
      else {
        const t = Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / len2));
        d = Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
      }
      if (d > worst) {
        worst = d;
        at = i;
      }
    }
    if (worst > tol) {
      keep[at] = 1;
      stack.push([a, at], [at, b]);
    }
  }
  return pts.filter((_, i) => keep[i]);
}

// Delta-code in hundredths of a degree: [x0, y0, dx1, dy1, ...]; consecutive duplicates (after rounding) are dropped.
function encode(pts) {
  const out = [];
  let px = 0;
  let py = 0;
  let n = 0;
  for (const [lon, lat] of pts) {
    const x = Math.round(lon * UNIT);
    const y = Math.round(lat * UNIT);
    if (n > 0 && x === px && y === py) continue;
    out.push(x - px, y - py);
    px = x;
    py = y;
    n++;
  }
  return n >= 2 ? out : null;
}

const coast = [];
const border = [];
let points = 0;
for (const [idx, ids] of uses) {
  const enc = encode(simplify(arcs[idx], TOLERANCE));
  if (!enc) continue;
  points += enc.length / 2;
  (ids.size > 1 ? border : coast).push(enc);
}

const json = JSON.stringify({ unit: UNIT, coast, border });
writeFileSync(OUT, json);
console.log(`coast arcs ${coast.length}, border arcs ${border.length}, points ${points}, ${json.length} bytes, tolerance ${TOLERANCE} deg`);
