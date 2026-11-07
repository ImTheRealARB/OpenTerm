/**
 * MAP: a world map you draw layers on. Ships (AISstream), ports and chokepoints (IMF PortWatch / AIS presets), earthquakes (USGS)
 * and natural events (NASA EONET) are layers; a layer is one file in `map/layers/` (see `map/layer.ts`).
 *
 * The map is drawn by this panel on a <canvas>: no map tiles, no web fonts, no map library, no network for the picture itself.
 * The coastline is Natural Earth public-domain data shipped inside the app (`map/worldData.json`, THIRD_PARTY.md). Only the
 * layers' data comes from the network, and each layer says where from and how old it is.
 *
 * Keys: arrows pan, + / - zoom, 0 whole world, 1-6 switch layers, J / K + Space pick a layer, N / P step through the dots
 * nearest the centre cross, Enter picks the one nearest the cross, C centres on the pick, V lists ships in the chokepoint box
 * nearest the cross (or the picked box), A loads aircraft over the FLT city nearest the cross, F5 reloads, Esc drops the pick. Mouse: drag pans, wheel zooms, click picks.
 * `MAP VESSELS HORMUZ` opens centred on a chokepoint with its ships; `MAP PORTS QUAKES` shows just those layers.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { registerPanelKeys } from "../keys/panelKeys";
import { usePanelRefresh } from "./panelRefresh";
import { hitTest, rankByCentre, type Item } from "../map/hit";
import type { MapLayer } from "../map/layer";
import { DEFAULT_ON, LAYERS } from "../map/layers";
import { parseMapArgs } from "../map/mapArgs";
import { clampView, fitBox, minZoom, nx, ny, panBy, unproject, viewBounds, worldPx, zoomAt, type Size, type View } from "../map/projection";
import type { LayerData, Shape, Tone } from "../map/types";
import { arcsInBounds, decodeArcs, type Arc } from "../map/worldMap";
import raw from "../map/worldData.json";
import "../map/map.css";
import { ApiError, keyRequiredOf } from "../net/core";
import type { GeoChokepoint } from "../net/types";
import { worldApi } from "../net/worldApi";
import { gauges } from "../perf/metrics";
import { displayVersion } from "../settings/runtime";
import { fmtAge, fmtLatLon } from "./aisArgs";
import { useLatest } from "../state/useLatest";
import type { FunctionProps } from "./registry";

// --- state ------------------------------------------------------------------------------------------------------------------
/** One load of one layer. Layers that cover one area at a time (vessels) have one part per area. */
interface Part {
  status: "loading" | "ok" | "err";
  data: LayerData | null;
  error: ApiError | null;
}
interface LayerState {
  on: boolean;
  parts: Record<string, Part>;
}
type States = Record<string, LayerState>;

const NO_PART: Part = { status: "loading", data: null, error: null };

function emptyStates(): States {
  return Object.fromEntries(LAYERS.map((l) => [l.id, { on: false, parts: {} }]));
}

/** Immutable update of one part. */
function patch(s: States, layer: string, area: string, f: (p: Part) => Part): States {
  const cur = s[layer];
  return { ...s, [layer]: { ...cur, parts: { ...cur.parts, [area]: f(cur.parts[area] ?? NO_PART) } } };
}

function asApiError(e: unknown): ApiError {
  return e instanceof ApiError ? e : new ApiError(0, e instanceof Error ? e.message : String(e), "unavailable");
}

// --- world outline (decoded once per page, on first use) ------------------------------------------------------------------------
let world: { coast: Arc[]; border: Arc[] } | null = null;
function outline() {
  world ??= { coast: decodeArcs(raw.coast, raw.unit), border: decodeArcs(raw.border, raw.unit) };
  return world;
}

// --- theme --------------------------------------------------------------------------------------------------------------------
interface Theme {
  bg: string;
  coast: string;
  border: string;
  grid: string;
  font: string;
  tone: Record<Tone, string>;
}
function readTheme(el: Element): Theme {
  const cs = getComputedStyle(el);
  const v = (n: string) => cs.getPropertyValue(n).trim();
  return {
    bg: v("--bg"), coast: v("--fg-dim"), border: v("--line"), grid: v("--bar") || v("--line"),
    font: `${v("--fs") || "12px"} ${v("--font")}`,
    tone: { fg: v("--fg"), dim: v("--fg-dim"), up: v("--up"), down: v("--down"), warn: v("--warn"), err: v("--err"), acc: v("--accent"), val: v("--val") || v("--fg") },
  };
}

const KEY_STEP = 0.25; // arrow keys pan a quarter of the canvas
const MAX_RANKED = 400; // N / P step through at most this many dots near the centre

/** The chokepoint whose centre is nearest to (lat, lon) in degrees: plain distance, good enough to pick an area. */
function nearestChokepoint(rows: GeoChokepoint[], lat: number, lon: number): GeoChokepoint | null {
  let best: GeoChokepoint | null = null;
  let bd = Infinity;
  for (const r of rows) {
    const d = (r.lat - lat) ** 2 + (r.lon - lon) ** 2;
    if (d < bd) {
      bd = d;
      best = r;
    }
  }
  return best;
}

export default function MAP({ panelId, args }: FunctionProps) {
  const parsed = useMemo(() => parseMapArgs(args), [args]);
  const [states, setStates] = useState<States>(emptyStates);
  const [cursor, setCursor] = useState(0); // layer list cursor
  const [sel, setSel] = useState<{ layer: string; id: string } | null>(null);
  const [msg, setMsg] = useState("");
  const [, setTick] = useState(0); // ages tick over every 15 s without refetching
  const [choke, setChoke] = useState<GeoChokepoint[]>([]);

  const box = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const centreText = useRef<HTMLSpanElement>(null);
  const view = useRef<View>({ lon: 10, lat: 25, zoom: 0 });
  const size = useRef<Size>({ w: 0, h: 0 });
  const theme = useRef<Theme | null>(null);
  const raf = useRef(0);
  const seq = useRef(new Map<string, number>());
  const dpr = useRef(1);

  // --- data: items (every shape of every layer that is on), where each shape came from ----------------------------------------------
  const { items, meta } = useMemo(() => {
    const list: Item[] = [];
    const from = new WeakMap<Shape, LayerData>();
    for (const l of [...LAYERS].reverse()) {
      const st = states[l.id];
      if (!st.on) continue;
      for (const area of Object.keys(st.parts)) {
        const d = st.parts[area].data;
        if (!d) continue;
        for (const shape of d.shapes) {
          list.push({ layer: l.id, shape });
          from.set(shape, d);
        }
      }
    }
    return { items: list, meta: from };
  }, [states]);

  const selected = useMemo(() => (sel ? items.find((i) => i.layer === sel.layer && i.shape.id === sel.id) ?? null : null), [items, sel]);
  const latest = useLatest({ items, selected, states, cursor, choke, parsed });

  // --- drawing: on demand, one frame at a time -------------------------------------------------------------------------------------
  const drawNow = useRef<() => void>(() => undefined);
  const requestDraw = useCallback(() => {
    if (raf.current) return;
    raf.current = requestAnimationFrame(() => {
      raf.current = 0;
      drawNow.current();
    });
  }, []);

  drawNow.current = () => {
    const ctx = canvas.current?.getContext("2d");
    const th = theme.current;
    const { w, h } = size.current;
    if (!ctx || !th || w === 0) return;
    const t0 = performance.now();
    const v = view.current;
    const W = worldPx(v.zoom);
    const ox = w / 2 - nx(v.lon) * W; // screen x = world x * W + ox
    const oy = h / 2 - ny(v.lat) * W;
    ctx.setTransform(dpr.current, 0, 0, dpr.current, 0, 0);
    ctx.fillStyle = th.bg;
    ctx.fillRect(0, 0, w, h);
    ctx.font = th.font;
    ctx.textBaseline = "middle";

    // graticule every 30 degrees
    ctx.strokeStyle = th.grid;
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let lon = -180; lon <= 180; lon += 30) {
      const x = Math.round(nx(lon) * W + ox) + 0.5;
      if (x >= 0 && x <= w) {
        ctx.moveTo(x, 0);
        ctx.lineTo(x, h);
      }
    }
    for (let lat = -60; lat <= 60; lat += 30) {
      const y = Math.round(ny(lat) * W + oy) + 0.5;
      if (y >= 0 && y <= h) {
        ctx.moveTo(0, y);
        ctx.lineTo(w, y);
      }
    }
    ctx.stroke();

    // borders (shared arcs) then coastlines: only arcs whose box touches the view, all in one path per colour
    const bounds = viewBounds(v, size.current);
    const o = outline();
    const strokeArcs = (arcs: Arc[], color: string) => {
      ctx.strokeStyle = color;
      ctx.beginPath();
      for (const a of arcsInBounds(arcs, bounds)) {
        const p = a.world;
        ctx.moveTo(p[0] * W + ox, p[1] * W + oy);
        for (let i = 2; i < p.length; i += 2) ctx.lineTo(p[i] * W + ox, p[i + 1] * W + oy);
      }
      ctx.stroke();
    };
    strokeArcs(o.border, th.border);
    strokeArcs(o.coast, th.coast);

    // layers, in registry order
    const { items: its, selected: pick } = latest.current;
    let dots = 0;
    for (const it of its) {
      const s = it.shape;
      const color = th.tone[s.tone];
      if (s.kind === "pt") {
        const x = nx(s.lon) * W + ox;
        const y = ny(s.lat) * W + oy;
        if (x < -20 || y < -20 || x > w + 20 || y > h + 20) continue;
        dots++;
        ctx.fillStyle = color;
        ctx.strokeStyle = th.bg; // a 1 px ring in the background colour keeps overlapping dots apart
        ctx.beginPath();
        ctx.arc(x, y, s.r, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
      } else if (s.kind === "line") {
        ctx.strokeStyle = color;
        ctx.beginPath();
        s.pts.forEach(([lon, lat], i) => {
          const x = nx(lon) * W + ox;
          const y = ny(lat) * W + oy;
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        });
        ctx.stroke();
      } else {
        const [south, west, north, east] = s.box;
        let x0 = nx(west) * W + ox;
        let x1 = nx(east) * W + ox;
        let y0 = ny(north) * W + oy;
        let y1 = ny(south) * W + oy;
        if (x1 < -50 || y1 < -50 || x0 > w + 50 || y0 > h + 50) continue;
        if (x1 - x0 < 8) {
          // zoomed far out a real box is under a pixel: draw a small square at its centre so the place is still visible
          const cx = (x0 + x1) / 2;
          x0 = cx - 4;
          x1 = cx + 4;
        }
        if (y1 - y0 < 8) {
          const cy = (y0 + y1) / 2;
          y0 = cy - 4;
          y1 = cy + 4;
        }
        ctx.strokeStyle = color;
        ctx.strokeRect(Math.round(x0) + 0.5, Math.round(y0) + 0.5, Math.round(x1 - x0), Math.round(y1 - y0));
        ctx.fillStyle = color;
        ctx.fillText(s.label, x0 + 2, y0 - 7);
      }
    }

    // the picked shape: a ring and its label
    if (pick) {
      const s = pick.shape;
      const x = nx(s.lon) * W + ox;
      const y = ny(s.lat) * W + oy;
      ctx.strokeStyle = th.tone.val;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(x, y, (s.kind === "pt" ? s.r : 5) + 4, 0, Math.PI * 2);
      ctx.stroke();
      ctx.lineWidth = 1;
      ctx.fillStyle = th.tone.val;
      const text = s.label.length > 48 ? `${s.label.slice(0, 47)}…` : s.label;
      const tw = ctx.measureText(text).width;
      const lx = Math.min(Math.max(x + 10, 2), w - tw - 4);
      ctx.fillStyle = th.bg;
      ctx.fillRect(lx - 2, y - 8, tw + 4, 16);
      ctx.fillStyle = th.tone.val;
      ctx.fillText(text, lx, y);
    }

    // the cross in the middle: where Enter, N / P and V measure from
    ctx.strokeStyle = th.tone.dim;
    ctx.beginPath();
    ctx.moveTo(w / 2 - 6, Math.round(h / 2) + 0.5);
    ctx.lineTo(w / 2 + 6, Math.round(h / 2) + 0.5);
    ctx.moveTo(Math.round(w / 2) + 0.5, h / 2 - 6);
    ctx.lineTo(Math.round(w / 2) + 0.5, h / 2 + 6);
    ctx.stroke();

    // numbers the DOM status line and the e2e tests read (the canvas itself is invisible to both)
    const ms = performance.now() - t0;
    gauges.set("map.drawMs", ms);
    gauges.set("map.zoom", v.zoom);
    gauges.set("map.centerLon", v.lon);
    gauges.set("map.centerLat", v.lat);
    gauges.set("map.shapes", its.length);
    gauges.set("map.dotsOnScreen", dots);
    if (centreText.current) centreText.current.textContent = `${fmtLatLon(v.lat, v.lon)} · ZOOM ${v.zoom.toFixed(1)}`;
  };

  /** Sets a view (clamped) and repaints. */
  const setView = useCallback(
    (next: View) => {
      view.current = clampView(next, size.current);
      requestDraw();
    },
    [requestDraw],
  );

  // --- loading -----------------------------------------------------------------------------------------------------------------------
  const loadPart = useCallback((layer: MapLayer, area: string | null, fresh: boolean) => {
    const key = `${layer.id}:${area ?? ""}`;
    const n = (seq.current.get(key) ?? 0) + 1;
    seq.current.set(key, n);
    const slot = area ?? "";
    setStates((s) => patch(s, layer.id, slot, (p) => ({ ...p, status: "loading" })));
    layer
      .load({ api: worldApi, fresh, area })
      .then((data) => {
        if (seq.current.get(key) === n) setStates((s) => patch(s, layer.id, slot, () => ({ status: "ok", data, error: null })));
      })
      .catch((e: unknown) => {
        // A failed reload keeps the last good data on the map, labelled STALE in the list: never blank, never silently old.
        if (seq.current.get(key) === n) setStates((s) => patch(s, layer.id, slot, (p) => ({ status: "err", data: p.data, error: asApiError(e) })));
      });
  }, []);

  /** The area a ship listen should use: the picked chokepoint box, else the box nearest the centre cross. */
  const areaForShips = useCallback((): string | null => {
    const { selected: pick, choke: rows } = latest.current;
    if (pick && pick.layer === "chokepoints") return pick.shape.id;
    return nearestChokepoint(rows, view.current.lat, view.current.lon)?.id ?? null;
  }, [latest]);

  /** The area a per-area layer should load: its own fixed list's nearest entry (flights), else the chokepoint rule above (vessels). */
  const areaFor = useCallback(
    (layer: MapLayer): string | null => (layer.nearestArea ? layer.nearestArea(view.current.lat, view.current.lon) : areaForShips()),
    [areaForShips],
  );

  const setLayerOn = useCallback(
    (layer: MapLayer, on: boolean, area: string | null = null) => {
      setStates((s) => ({ ...s, [layer.id]: { ...s[layer.id], on } }));
      if (!on) return;
      const st = latest.current.states[layer.id];
      if (layer.perArea) {
        const a = area ?? areaFor(layer);
        if (!a) setMsg(`${layer.name}: THE CHOKEPOINT LIST HAS NOT LOADED YET, PRESS ${layer.loadKey ?? "THE LOAD KEY"} IN A MOMENT`);
        else if (!st.parts[a]) loadPart(layer, a, false);
      } else if (Object.keys(st.parts).length === 0) loadPart(layer, null, false);
    },
    [latest, loadPart, areaFor],
  );

  // Chokepoint list: needed for MAP <AREA> and for V. Tiny and static, cached by the api layer.
  useEffect(() => {
    let live = true;
    worldApi
      .geoChokepoints()
      .then((e) => live && setChoke(e.data.rows))
      .catch((e: unknown) => live && setMsg(`CHOKEPOINT LIST: ${asApiError(e).message}`));
    return () => {
      live = false;
    };
  }, []);

  // Apply the command's words. Layers named = exactly those; none named = the default set. An area centres the map on its box
  // (and, with VESSELS, listens for its ships). Waits for the chokepoint list when an area was typed.
  const argKey = args.join(" ").toUpperCase();
  const applied = useRef("");
  useEffect(() => {
    if (parsed.error) return;
    if (parsed.area && choke.length === 0) return; // run again when the list arrives
    const stamp = `${argKey}|${choke.length > 0}`;
    if (applied.current === stamp) return;
    applied.current = stamp;
    const want = new Set(parsed.layers ?? DEFAULT_ON);
    if (parsed.area) want.add("chokepoints"); // an area is a box: show the box, so the place is on the map
    // With only an area typed (MAP HORMUZ) keep the default layers; the area is where to look.
    for (const l of LAYERS) {
      if (want.has(l.id)) setLayerOn(l, true, l.perArea && !l.nearestArea ? parsed.area : null); // a typed chokepoint is for vessels only
      else setStates((s) => (s[l.id].on ? { ...s, [l.id]: { ...s[l.id], on: false } } : s));
    }
    const row = parsed.area ? choke.find((c) => c.id === parsed.area) : null;
    if (row) {
      view.current = fitBox(row.box, size.current, 130);
      setSel({ layer: "chokepoints", id: row.id });
      requestDraw();
    }
  }, [argKey, parsed, choke, setLayerOn, requestDraw]);

  // Timed refresh for the layers that have a rule (quakes 2 min, events 10 min, ports hourly).
  const onKey = LAYERS.filter((l) => states[l.id].on && l.refreshMs > 0).map((l) => l.id).join(",");
  useEffect(() => {
    const timers = LAYERS.filter((l) => onKey.split(",").includes(l.id)).map((l) => setInterval(() => loadPart(l, null, false), l.refreshMs));
    return () => timers.forEach(clearInterval);
  }, [onKey, loadPart]);
  useEffect(() => {
    const t = setInterval(() => setTick((n) => n + 1), 15_000);
    return () => clearInterval(t);
  }, []);

  // repaint when shapes or the pick change
  useEffect(() => requestDraw(), [items, selected, requestDraw]);

  // --- canvas, size, mouse ---------------------------------------------------------------------------------------------------
  useEffect(() => {
    const el = box.current;
    const cv = canvas.current;
    if (!el || !cv) return;
    theme.current = readTheme(el);
    const resize = () => {
      const r = el.getBoundingClientRect();
      const w = Math.max(1, Math.floor(r.width));
      const h = Math.max(1, Math.floor(r.height));
      dpr.current = window.devicePixelRatio || 1;
      cv.width = Math.floor(w * dpr.current);
      cv.height = Math.floor(h * dpr.current);
      const first = size.current.w === 0;
      size.current = { w, h };
      // first size: the whole world; afterwards keep what the user is looking at
      view.current = clampView(first ? { lon: 10, lat: 25, zoom: minZoom(size.current) } : view.current, size.current);
      requestDraw();
    };
    const ro = new ResizeObserver(resize);
    ro.observe(el);
    resize();

    let drag: { x: number; y: number; moved: number } | null = null;
    const local = (e: MouseEvent): [number, number] => {
      const r = cv.getBoundingClientRect();
      return [e.clientX - r.left, e.clientY - r.top];
    };
    const onDown = (e: MouseEvent) => {
      drag = { x: e.clientX, y: e.clientY, moved: 0 };
    };
    const onMove = (e: MouseEvent) => {
      if (drag) {
        const dx = e.clientX - drag.x;
        const dy = e.clientY - drag.y;
        drag.moved += Math.abs(dx) + Math.abs(dy);
        drag.x = e.clientX;
        drag.y = e.clientY;
        if (drag.moved > 4) setView(panBy(view.current, size.current, dx, dy));
      }
    };
    const onUp = (e: MouseEvent) => {
      const d = drag;
      drag = null;
      if (!d || d.moved > 4) return;
      // a click that did not drag: pick what is under it
      const [px, py] = local(e);
      const hit = hitTest(latest.current.items, view.current, size.current, px, py);
      setSel(hit ? { layer: hit.layer, id: hit.shape.id } : null);
    };
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const [px, py] = local(e);
      setView(zoomAt(view.current, size.current, px, py, Math.max(-1, Math.min(1, -e.deltaY * 0.0025))));
    };
    const onHover = (e: MouseEvent) => {
      if (drag) return;
      const [px, py] = local(e);
      const [lon, lat] = unproject(view.current, size.current, px, py);
      cv.title = fmtLatLon(lat, lon);
    };
    cv.addEventListener("mousedown", onDown);
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    cv.addEventListener("mousemove", onHover);
    cv.addEventListener("wheel", onWheel, { passive: false });
    const unsubTheme = displayVersion.subscribe(() => {
      theme.current = readTheme(el);
      requestDraw();
    });
    return () => {
      ro.disconnect();
      cv.removeEventListener("mousedown", onDown);
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      cv.removeEventListener("mousemove", onHover);
      cv.removeEventListener("wheel", onWheel);
      unsubTheme();
      if (raf.current) cancelAnimationFrame(raf.current);
      raf.current = 0;
    };
  }, [requestDraw, setView, latest]);

  // --- keys --------------------------------------------------------------------------------------------------------------------------
  // Refresh (F5, the Refresh button): reload every layer that is switched on, per area where the layer has areas.
  usePanelRefresh(panelId, () => {
    for (const l of LAYERS) {
      const st = latest.current.states[l.id];
      if (!st.on) continue;
      if (l.perArea) Object.keys(st.parts).forEach((a) => loadPart(l, a, true));
      else loadPart(l, null, true);
    }
  });
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        if (e.ctrlKey || e.altKey || e.metaKey) return false;
        const { w, h } = size.current;
        const cur = view.current;
        const L = latest.current;
        const k = e.key;
        if (k === "ArrowLeft" || k === "ArrowRight" || k === "ArrowUp" || k === "ArrowDown") {
          // the arrow names the direction you want to look: Right shows more east, so the map slides left
          const step = KEY_STEP * (e.shiftKey ? 2 : 1);
          const dx = k === "ArrowLeft" ? w * step : k === "ArrowRight" ? -w * step : 0;
          const dy = k === "ArrowUp" ? h * step : k === "ArrowDown" ? -h * step : 0;
          setView(panBy(cur, size.current, dx, dy));
          return true;
        }
        if (k === "+" || k === "=" || k === "-" || k === "_") {
          setView(zoomAt(cur, size.current, w / 2, h / 2, k === "+" || k === "=" ? 1 : -1)); // zoom about the centre cross
          return true;
        }
        if (k === "0") {
          setView({ lon: 10, lat: 25, zoom: minZoom(size.current) }); // the whole world
          return true;
        }
        const byKey = LAYERS.find((l) => l.key === k);
        if (byKey) {
          setLayerOn(byKey, !L.states[byKey.id].on);
          setCursor(LAYERS.indexOf(byKey));
          return true;
        }
        if (k === "j" || k === "k") {
          setCursor((c) => (c + (k === "j" ? 1 : -1) + LAYERS.length) % LAYERS.length);
          return true;
        }
        if (k === " ") {
          const l = LAYERS[L.cursor];
          setLayerOn(l, !L.states[l.id].on);
          return true;
        }
        if (k === "n" || k === "p") {
          const ranked = rankByCentre(L.items, cur, size.current, MAX_RANKED);
          if (ranked.length === 0) return true;
          const at = L.selected ? ranked.findIndex((i) => i.shape === L.selected!.shape) : -1;
          const next = at < 0 ? ranked[0] : ranked[(at + (k === "n" ? 1 : -1) + ranked.length) % ranked.length];
          setSel({ layer: next.layer, id: next.shape.id });
          return true;
        }
        if (k === "Enter") {
          if (L.selected) {
            // a second Enter on a pick centres on it, zoomed in enough to tell neighbours apart
            setView({ lon: L.selected.shape.lon, lat: L.selected.shape.lat, zoom: Math.max(cur.zoom, 6) });
            return true;
          }
          const first = rankByCentre(L.items, cur, size.current, 1)[0];
          if (first) setSel({ layer: first.layer, id: first.shape.id });
          else setMsg("NOTHING ON SCREEN TO PICK: PAN OR ZOOM, OR SWITCH A LAYER ON");
          return true;
        }
        if (k === "c") {
          if (L.selected) setView({ lon: L.selected.shape.lon, lat: L.selected.shape.lat, zoom: Math.max(cur.zoom, 6) });
          return true;
        }
        if (k === "Escape") {
          if (!L.selected) return false;
          setSel(null);
          return true;
        }
        // Each per-area layer has its own load key: V = ships (chokepoint box), A = aircraft (city box).
        const areaLayer = LAYERS.find((l) => l.perArea && l.loadKey && l.loadKey.toLowerCase() === k.toLowerCase());
        if (areaLayer) {
          const a = areaFor(areaLayer);
          if (!a) {
            setMsg(`${areaLayer.loadKey}: THE CHOKEPOINT LIST HAS NOT LOADED YET`);
            return true;
          }
          setStates((s) => ({ ...s, [areaLayer.id]: { ...s[areaLayer.id], on: true } }));
          setMsg(`${areaLayer.loadKey}: LOADING ${areaLayer.loadLabel ?? areaLayer.name} FOR ${a}`);
          loadPart(areaLayer, a, true);
          return true;
        }
        return false;
      }),
    [panelId, latest, setView, setLayerOn, loadPart, areaFor],
  );

  // --- the side lists ------------------------------------------------------------------------------------------------------------------
  const nowSec = Date.now() / 1000;
  const layerLine = (l: MapLayer): { text: string; tone: string } => {
    const st = states[l.id];
    if (!st.on) return { text: "OFF", tone: "dim" };
    const parts = Object.values(st.parts);
    if (parts.length === 0) return { text: l.perArea ? `NO AREA YET: PRESS ${l.loadKey ?? "ITS KEY"}` : "…", tone: "dim" };
    const err = parts.find((p) => p.status === "err");
    const data = parts.filter((p) => p.data);
    const count = data.reduce((n, p) => n + (p.data?.shapes.length ?? 0), 0);
    if (err) {
      const kr = keyRequiredOf(err.error);
      if (kr && !err.data) return { text: `KEY REQUIRED: set ${kr.key ?? l.needsKey ?? "A KEY"} in APIKEYS`, tone: "warn" };
      return { text: `${err.data ? `STALE ${count}` : "ERR"} · ${err.error?.message ?? "FAILED"}`, tone: "err" };
    }
    if (parts.some((p) => p.status === "loading")) return { text: count ? `${count} · RELOADING` : "LOADING…", tone: "dim" };
    const oldest = Math.min(...data.map((p) => p.data!.asOf));
    const flags = [data.some((p) => p.data!.stale) ? "STALE" : "", data.some((p) => p.data!.fixture) ? "FIXTURE" : ""].filter(Boolean).join(" ");
    return { text: `${count} · ${fmtAge(nowSec - oldest)}${flags ? ` · ${flags}` : ""}`, tone: flags ? "warn" : "fg" };
  };

  const cl = LAYERS[cursor];
  const notes = LAYERS.filter((l) => states[l.id].on).flatMap((l) =>
    Object.values(states[l.id].parts).flatMap((p) => (p.data?.notes ?? []).map((t) => `${l.name}: ${t}`)),
  );
  const uniqueNotes = [...new Set(notes)];
  const pickLayer = selected ? LAYERS.find((l) => l.id === selected.layer) : null;
  const pickData = selected ? meta.get(selected.shape) : null;
  const srText = selected ? `SELECTED ${pickLayer?.name ?? ""} ${selected.shape.label} ${fmtLatLon(selected.shape.lat, selected.shape.lon)}` : "";

  return (
    <div className="fn">
      <div className="line">
        <span className="acc">MAP</span> <span ref={centreText} />
        <span className="dim"> · ARROWS PAN · +/- ZOOM · 1-6 LAYERS · N/P STEP · ENTER PICK · V SHIPS · A AIRCRAFT · F5 RELOAD</span>
        {msg && <span className="warn"> · {msg}</span>}
      </div>
      {parsed.error && <div className="err">{parsed.error}</div>}
      <div className="map-body">
        <div className="map-canvas" ref={box}>
          <canvas ref={canvas} aria-hidden="true" data-testid="map-canvas" />
          <div className="sr" role="status" aria-live="polite" data-testid="map-sr">
            {srText}
          </div>
        </div>
        <div className="map-side" data-testid="map-side">
          <div className="mhd">LAYERS · J/K SPACE</div>
          {LAYERS.map((l, i) => {
            const line = layerLine(l);
            return (
              <div key={l.id} className={`row${i === cursor ? " on" : ""}`} data-testid={`map-layer-${l.id}`} data-on={states[l.id].on ? "1" : "0"} onClick={() => { setCursor(i); setLayerOn(l, !states[l.id].on); }}>
                {l.key} {l.name.padEnd(12)} <span className={line.tone}>{line.text}</span>
              </div>
            );
          })}
          <div className="note" data-testid="map-layer-card">
            <div>SOURCE {cl.source}</div>
            <div>SHAPES {cl.shapes}</div>
            <div>COLOUR {cl.colour}</div>
            <div>REFRESH {cl.refresh}</div>
            {cl.needsKey && <div>NEEDS KEY {cl.needsKey} (APIKEYS)</div>}
          </div>
          <div className="mhd">{selected ? `PICKED · ${pickLayer?.name}` : "PICKED · NONE (ENTER, N/P OR CLICK)"}</div>
          {selected && (
            <div data-testid="map-detail">
              {selected.shape.detail.map(([k, v]) => (
                <div key={k} className="kv">
                  <span>{k}</span>
                  <span>{v}</span>
                </div>
              ))}
              <div className="kv"><span>POSITION</span><span>{fmtLatLon(selected.shape.lat, selected.shape.lon)}</span></div>
              <div className="kv"><span>SOURCE</span><span>{pickData?.source ?? ""}</span></div>
              {selected.shape.time != null && <div className="kv"><span>OBSERVED</span><span>{fmtAge(nowSec - selected.shape.time)} AGO</span></div>}
              {pickData && <div className="kv"><span>FETCHED</span><span>{fmtAge(nowSec - pickData.asOf)} AGO{pickData.stale ? " · STALE" : ""}{pickData.fixture ? " · TEST DATA" : ""}</span></div>}
            </div>
          )}
          {uniqueNotes.map((t) => (
            <div key={t} className={`note${t.includes("DOC-SHAPED") ? " warn" : ""}`}>{t}</div>
          ))}
        </div>
      </div>
    </div>
  );
}
