/**
 * The GP-only layer of ChartView.
 *
 * ChartView is a plain price chart (candles / line, volume, readout, pan / zoom / crosshair, live ticks).
 * GP (and PERF CHART) additionally want: technical indicators computed in a Web Worker, library and
 * formula indicators (IND), pattern + event markers, user drawings on an overlay canvas, extra symbols in
 * their own panes, dashed alert lines and click-to-pick. All of that lives here and is switched on only when
 * a caller passes the `gp` prop to ChartView. FRED, ECO, BT, MF and the other line charts never pass it,
 * so they never create the overlay canvas, the marker plugin or the indicator worker.
 *
 * How it plugs in (a "layer" is just a hook plus a small set of hand-over points):
 *  - ChartView calls `useGpLayer(...)` AFTER its own series effect. React runs effects in the order they are
 *    written, and the indicator effects below must run after the series effect (a rebuild clears the
 *    indicator bookkeeping, then these effects re-add what is wanted). Do not move the call above it.
 *  - The hook publishes its hand-over points in `gpRef.current` during render. ChartView's series effect calls
 *    `reset`, `afterMain`, `afterPanes` and `seriesCount` on it; the readout calls `eventText`; the click
 *    handler is `onClick`. `gpRef.current` is null when `gp` was not passed, and every call site checks that.
 *  - Behaviour is unchanged from when this code lived inside ChartView: same effect order, same effect
 *    dependency lists, same gauges (`chart.extraSeries / panes / markers / events / alertLines / drawSegs`).
 */
import { useEffect, useRef, type MouseEvent, type RefObject } from "react";
import {
  HistogramSeries, LineSeries, LineStyle, createSeriesMarkers,
  type IChartApi, type ISeriesApi, type ISeriesMarkersPluginApi, type Logical, type SeriesMarker, type SeriesType, type Time,
} from "lightweight-charts";
import { fmtPrice } from "../format";
import { gauges } from "../perf/metrics";
import type { IndicatorName } from "./indicators";
import { diffIndicators } from "./indicatorDiff";
import { hitTest, segments, timeToLogical, type DPoint, type DrawKind, type Drawing, type Geo } from "./drawings";
import { PATTERN_INFO } from "./patterns";
import type { LibraryRes } from "./libraryWorker";
import { toTime, type BarData, type ThemeColors } from "./chartBase";
import type { ChartType } from "./chartTypes";

/** Phase 19 drawings overlay state, owned by GP. `pending` is a drawing being placed: its anchors so far; the cursor is the next one. */
export interface DrawState {
  drawings: Drawing[];
  selected: string | null;
  pending: { kind: DrawKind; pts: DPoint[]; anchor: "C" | "H" | "L" | "O" } | null;
}

/** An event marker already snapped to a bar time (E earnings, D ex-dividend, S split). */
export interface ChartMarkerEvent {
  t: number;
  kind: "E" | "D" | "S";
  detail: string;
}

/** One library indicator (`id` + `params`) or formula on the chart. `key` is stable (`LIB:ATR:14`, `F:<encoded formula>`); `label` titles its series. */
export interface CustomItem {
  key: string;
  label: string;
  id?: string;
  params?: number[];
  formula?: string;
}

/** Everything GP adds on top of the plain chart. Passed to ChartView as the single `gp` prop. */
export interface GpLayerProps {
  indicators: IndicatorName[];
  /** Phase 19: extra symbols, each in its own pane below the price pane (raw prices, own scale). */
  comparePanes?: { symbol: string; t: Float64Array; c: Float64Array }[];
  draw?: DrawState;
  events?: ChartMarkerEvent[];
  /** Mouse click on the chart: the drawing under the pointer (or null). */
  onPick?: (id: string | null) => void;
  /** Active price alerts of this symbol, drawn as dashed "ALRT" lines. Their changes never rebuild the chart. */
  alertLevels?: number[];
  /** Alt+click on the chart, or any click while `pickArmed`: the price under the pointer. */
  onPickPrice?: (price: number) => void;
  pickArmed?: boolean;
  /** Library indicators and formulas (IND). Diffed by `key` like `indicators`: a change adds or removes only that entry's series. */
  custom?: CustomItem[];
  /** Worker errors per custom key ("FORMULA ERROR: ... AT 12"); called when the set of errors changes. */
  onCustomErrors?: (errors: Record<string, string>) => void;
}

/** The parts of ChartView's state the layer reads. All refs, so reading them is always current. */
export interface ChartCore {
  box: RefObject<HTMLDivElement | null>;
  chartRef: RefObject<IChartApi | null>;
  /** The price series (null before the first build). */
  main: RefObject<ISeriesApi<SeriesType> | null>;
  colors: RefObject<ThemeColors>;
  dataRef: RefObject<BarData>;
  /** The keyboard crosshair. */
  cross: RefObject<{ on: boolean; idx: number }>;
  /** The animation-frame handle shared with ChartView's pan / zoom / resize repaint. */
  rafRef: RefObject<number>;
  /** ChartView calls this after every pan / zoom / resize / crosshair move; the layer sets it to its overlay painter. */
  paintRef: RefObject<() => void>;
  /** Rewrites the O/H/L/C/V readout line for bar `i`. */
  writeRef: RefObject<(i: number) => void>;
  /** Refreshes the `chart.extraSeries` / `chart.panes` gauges. */
  publish: () => void;
}

/** The inputs whose change makes ChartView rebuild its series. The layer's effects re-run on exactly these (as before). */
export interface GpBuildInputs {
  data: BarData;
  compare: { symbol: string; t: Float64Array; c: Float64Array } | null | undefined;
  type: ChartType;
  log: boolean;
  lowerPane: { title: string; v: Float64Array } | null | undefined;
  ver: number;
}

/** What ChartView's own code may call on the layer (see the file header). */
export interface GpOps {
  /** Called inside the series rebuild, after the plain series were removed: removes this layer's series and forgets its state. */
  reset(chart: IChartApi): void;
  /** Called right after the price series was created: attaches the marker plugin. */
  afterMain(s: ISeriesApi<SeriesType>): void;
  /** Called after the plain extra panes were added; `firstPane` is the next free pane index. Adds the compare panes. */
  afterPanes(chart: IChartApi, firstPane: number): void;
  /** How many series the layer has on the chart (for the `chart.extraSeries` gauge). */
  seriesCount(): number;
  /** The "[E | D ...]" suffix of the readout for bar `i`. */
  eventText(i: number): string;
  /** Click handler for the chart box (pick a price for an alert, or pick a drawing). */
  onClick(e: MouseEvent<HTMLDivElement>): void;
}

export function useGpLayer(
  core: ChartCore,
  gpRef: RefObject<GpOps | null>,
  gp: GpLayerProps | undefined,
  build: GpBuildInputs,
): { overlay: RefObject<HTMLCanvasElement | null> } {
  const { box, chartRef, main, colors, dataRef, cross, rafRef, paintRef, writeRef, publish } = core;
  const { data, compare, type, log, lowerPane, ver } = build;
  const indicators = gp?.indicators;
  const comparePanes = gp?.comparePanes;
  const draw = gp?.draw;
  const events = gp?.events;
  const alertLevels = gp?.alertLevels;
  const custom = gp?.custom;

  const worker = useRef<Worker | null>(null);
  const reqId = useRef(0);
  // The overlay canvas (drawings) and the marker plugin of the price series.
  const overlay = useRef<HTMLCanvasElement>(null);
  const markersApi = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  // Indicators drawn so far, by name: their series and pattern marks. A toggle touches only its own entry.
  const ind = useRef(new Map<IndicatorName, { series: ISeriesApi<SeriesType>[]; marks: SeriesMarker<Time>[] }>());
  // Worker request id -> the indicators asked for in that one message.
  const indReq = useRef(new Map<number, IndicatorName[]>());
  const indWant = useRef(new Set<IndicatorName>());
  // Library / formula indicators, by key; same lifecycle as `ind` (own requests to the same worker).
  const lib = useRef(new Map<string, ISeriesApi<SeriesType>[]>());
  const libReq = useRef(new Map<number, string[]>());
  const libWant = useRef(new Set<string>());
  const libErr = useRef(new Map<string, string>());
  // The extra-symbol panes (comparePanes), one line series each.
  const paneSeries = useRef<ISeriesApi<SeriesType>[]>([]);
  const basePanes = useRef(1);
  const customRef = useRef<CustomItem[]>([]);
  customRef.current = custom ?? [];
  const errCb = useRef(gp?.onCustomErrors);
  errCb.current = gp?.onCustomErrors;
  const onLibResult = useRef<(m: LibraryRes) => void>(() => {});
  const onIndResult = useRef<(id: number, parts: Partial<Record<IndicatorName, Record<string, Float64Array>>>) => void>(() => {});
  const eventsRef = useRef<ChartMarkerEvent[] | undefined>(events);
  eventsRef.current = events;
  const drawRef = useRef<DrawState | undefined>(draw);
  drawRef.current = draw;
  const pickRef = useRef({ armed: false, cb: gp?.onPickPrice });
  pickRef.current = { armed: !!gp?.pickArmed, cb: gp?.onPickPrice };
  const compareOn = useRef(false);
  compareOn.current = !!compare;
  const geoRef = useRef<Geo | null>(null);

  // The worker belongs to the layer: it is stopped when the chart goes away.
  useEffect(
    () => () => {
      worker.current?.terminate();
      worker.current = null;
    },
    [],
  );

  /** Runs `fn` (series added or removed) and puts the visible range back if lightweight-charts moved it. */
  function keepRange(fn: () => void) {
    const ts = chartRef.current?.timeScale();
    const before = ts?.getVisibleLogicalRange();
    fn();
    if (!ts || !before) return;
    const after = ts.getVisibleLogicalRange();
    if (!after || Math.abs(after.from - before.from) > 1e-6 || Math.abs(after.to - before.to) > 1e-6) ts.setVisibleLogicalRange(before);
  }

  function layoutPanes(ch: IChartApi) {
    const panes = ch.panes();
    for (let i = panes.length - 1; i >= 1; i--) if (panes[i].getSeries().length === 0) ch.removePane(i);
    const rest = ch.panes();
    for (let i = 1; i < rest.length; i++) rest[i].setHeight(i < basePanes.current ? 110 : 90);
  }

  /** Pattern marks and event marks share the price series' marker plugin. */
  function applyMarkers() {
    const api = markersApi.current;
    if (!api) return;
    const c = colors.current;
    const ev: SeriesMarker<Time>[] = (eventsRef.current ?? []).map((e) => ({ time: toTime(e.t), position: "aboveBar", shape: "square", color: c.fg, text: e.kind }));
    const pat = [...ind.current.values()].flatMap((e) => e.marks);
    const all = [...pat, ...ev];
    all.sort((a, b) => (a.time as number) - (b.time as number));
    api.setMarkers(all);
    gauges.set("chart.markers", pat.length);
    gauges.set("chart.events", ev.length);
  }

  function ensureWorker() {
    if (worker.current) return worker.current;
    const w = new Worker(new URL("./indicators.worker.ts", import.meta.url), { type: "module" });
    w.onmessage = (ev: MessageEvent<{ type?: string; id: number; parts: Partial<Record<IndicatorName, Record<string, Float64Array>>> }>) => {
      if (ev.data.type === "library") onLibResult.current(ev.data as unknown as LibraryRes);
      else onIndResult.current(ev.data.id, ev.data.parts);
    };
    worker.current = w;
    return w;
  }

  // ---- hand-over points called by ChartView (published below) ----
  const ops: GpOps = {
    reset(chart) {
      for (const s of [...paneSeries.current, ...[...ind.current.values()].flatMap((e) => e.series), ...[...lib.current.values()].flat()]) chart.removeSeries(s);
      paneSeries.current = [];
      ind.current.clear();
      indReq.current.clear();
      indWant.current.clear();
      lib.current.clear();
      libReq.current.clear();
      libWant.current.clear();
      if (libErr.current.size) {
        libErr.current.clear();
        errCb.current?.({});
      }
    },
    afterMain(s) {
      markersApi.current = createSeriesMarkers(s, []);
      applyMarkers();
    },
    afterPanes(chart, firstPane) {
      (comparePanes ?? []).forEach((cp, k) => {
        const pane = firstPane + k;
        const ls = chart.addSeries(LineSeries, { color: colors.current.acc, lineWidth: 1, priceLineVisible: false, title: cp.symbol }, pane);
        const pts = [];
        for (let i = 0; i < cp.t.length; i++) if (Number.isFinite(cp.c[i])) pts.push({ time: toTime(cp.t[i]), value: cp.c[i] });
        ls.setData(pts);
        paneSeries.current.push(ls);
        chart.panes()[pane]?.setHeight(110);
      });
      basePanes.current = firstPane + (comparePanes?.length ?? 0);
    },
    seriesCount() {
      let n = paneSeries.current.length;
      for (const e of ind.current.values()) n += e.series.length;
      for (const s of lib.current.values()) n += s.length;
      return n;
    },
    eventText(i) {
      const t = data.t[i];
      const hit = (events ?? []).filter((e) => e.t === t);
      return hit.length ? "  [" + hit.map((e) => e.detail).join(" | ") + "]" : "";
    },
    onClick(e) {
      const pk = pickRef.current;
      if (pk.cb && (pk.armed || e.altKey) && main.current && !compareOn.current) {
        const r = e.currentTarget.getBoundingClientRect();
        const px = main.current.coordinateToPrice(e.clientY - r.top);
        pk.cb(px === null ? NaN : (px as number));
        return;
      }
      const g = geoRef.current;
      const d = drawRef.current;
      const onPick = gp?.onPick;
      if (!g || !d || !onPick || compareOn.current) return;
      const r = e.currentTarget.getBoundingClientRect();
      onPick(hitTest(d.drawings, e.clientX - r.left, e.clientY - r.top, g, 6));
    },
  };
  gpRef.current = gp ? ops : null;

  // Alert lines: dashed "ALRT" price lines on the price series. Re-created after a rebuild (the series is new); a level change
  // touches only these lines, never the series, so zoom and the indicator toggles stay untouched.
  const levelsKey = (alertLevels ?? []).join(",");
  useEffect(() => {
    if (!gp) return;
    const s = main.current;
    const levels = levelsKey ? levelsKey.split(",").map(Number) : [];
    gauges.set("chart.alertLines", 0);
    if (!s || compareOn.current || !levels.length) return;
    const c = colors.current;
    const lines = levels.map((price) => s.createPriceLine({ price, color: c.warn, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: "ALRT" }));
    gauges.set("chart.alertLines", lines.length);
    return () => {
      gauges.set("chart.alertLines", 0);
      for (const l of lines) {
        try {
          s.removePriceLine(l);
        } catch {
          /* the series was already replaced by a rebuild */
        }
      }
    };
  // Same dependency list as before the split: the rebuild inputs plus the alert levels.
  // eslint-disable-next-line react-hooks/exhaustive-deps -- re-run on rebuild inputs + levels; `gp` only says whether the layer is on
  }, [levelsKey, data, compare, type, log, lowerPane, comparePanes, ver]);

  // Indicators: a toggle adds or removes only that indicator's series (and its pane); zoom and scroll stay.
  // Runs after the series effect in ChartView, which clears `indWant` whenever it rebuilds, so a rebuild re-adds them all.
  useEffect(() => {
    const ch = chartRef.current;
    if (!ch || !indicators) return;
    const { add, remove } = diffIndicators(indWant.current, indicators);
    if (!remove.length && !(add.length && data.c.length)) return;
    keepRange(() => {
      for (const name of remove) {
        for (const s of ind.current.get(name)?.series ?? []) ch.removeSeries(s);
        ind.current.delete(name);
        indWant.current.delete(name);
        for (const [id, names] of indReq.current) {
          const rest = names.filter((n) => n !== name);
          if (rest.length) indReq.current.set(id, rest);
          else indReq.current.delete(id);
        }
      }
      if (remove.length) {
        layoutPanes(ch);
        applyMarkers();
        publish();
      }
    });
    if (add.length && data.c.length) {
      // Started on the first indicator request: charts without a GP layer never pay for the worker.
      ensureWorker();
      // ONE message for the whole batch: the six bar arrays are copied once, not once per indicator.
      const id = ++reqId.current;
      indReq.current.set(id, add);
      for (const name of add) indWant.current.add(name);
      // Copies: the worker gets its own buffers so `data` stays usable here.
      ensureWorker().postMessage({ id, which: add, series: { t: data.t.slice(), o: data.o.slice(), h: data.h.slice(), l: data.l.slice(), c: data.c.slice(), v: data.v.slice() } });
    }
  // Same dependency list as before the split. The helper functions are re-created every render and read refs, so they are not deps.
  // eslint-disable-next-line react-hooks/exhaustive-deps -- re-run on indicators + rebuild inputs only
  }, [indicators, data, compare, type, log, lowerPane, comparePanes, ver]);

  // Library / formula indicators: the same add/remove-only-this-entry rule, one worker request for a batch of adds.
  const customKey = (custom ?? []).map((x) => x.key).join("\n");
  useEffect(() => {
    const ch = chartRef.current;
    if (!ch || !gp) return;
    const items = customRef.current;
    const { add, remove } = diffIndicators(libWant.current, items.map((x) => x.key));
    if (!remove.length && !(add.length && data.c.length)) return;
    if (remove.length) {
      keepRange(() => {
        for (const key of remove) {
          for (const s of lib.current.get(key) ?? []) ch.removeSeries(s);
          lib.current.delete(key);
          libWant.current.delete(key);
          libErr.current.delete(key);
        }
        for (const [id, keys] of libReq.current) {
          const rest = keys.filter((k) => !remove.includes(k));
          if (rest.length) libReq.current.set(id, rest);
          else libReq.current.delete(id);
        }
        layoutPanes(ch);
        publish();
      });
      errCb.current?.(Object.fromEntries(libErr.current));
    }
    if (add.length && data.c.length) {
      const id = ++reqId.current;
      const send = items.filter((x) => add.includes(x.key)).slice(0, 20);
      libReq.current.set(id, send.map((x) => x.key));
      for (const x of send) libWant.current.add(x.key);
      ensureWorker().postMessage({
        type: "library",
        id,
        series: { t: data.t.slice(), o: data.o.slice(), h: data.h.slice(), l: data.l.slice(), c: data.c.slice(), v: data.v.slice() },
        items: send.map((x) => ({ key: x.key, id: x.id, params: x.params, formula: x.formula })),
      });
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps -- re-run on the custom keys + rebuild inputs only
  }, [customKey, data, compare, type, log, lowerPane, comparePanes, ver]);

  onLibResult.current = (m) => {
    const ch = chartRef.current;
    const keys = libReq.current.get(m.id);
    if (!ch || !keys) return;
    libReq.current.delete(m.id);
    const c = colors.current;
    const t = dataRef.current.t;
    const palette = [c.acc, c.warn, c.fg, c.up, c.down, c.dim];
    let errChanged = false;
    keepRange(() => {
      for (const key of keys) {
        const r = m.results[key];
        const item = customRef.current.find((x) => x.key === key);
        if (!r || !item || !libWant.current.has(key)) continue;
        if (!r.ok) {
          libErr.current.set(key, `${item.formula !== undefined ? "FORMULA" : "INDICATOR"} ERROR: ${r.error}`);
          errChanged = true;
          continue;
        }
        const pane = r.pane === "price" ? 0 : ch.panes().length;
        const mine: ISeriesApi<SeriesType>[] = [];
        r.data.forEach((vals, j) => {
          const ls = ch.addSeries(LineSeries, { color: palette[j % palette.length], lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, title: j === 0 ? item.label : r.outputs[j] ?? "" }, pane);
          const pts = [];
          for (let i = 0; i < vals.length && i < t.length; i++) pts.push(Number.isFinite(vals[i]) ? { time: toTime(t[i]), value: vals[i] } : { time: toTime(t[i]) });
          ls.setData(pts);
          mine.push(ls);
        });
        lib.current.set(key, mine);
      }
      layoutPanes(ch);
      publish();
    });
    if (errChanged) errCb.current?.(Object.fromEntries(libErr.current));
  };

  onIndResult.current = (id, parts) => {
    const names = indReq.current.get(id);
    const ch = chartRef.current;
    if (names === undefined || !ch) return;
    indReq.current.delete(id);
    keepRange(() => {
      // Draw each indicator from its own group of outputs, then lay out panes / marks / publish ONCE.
      for (const name of names) {
        const r = parts[name];
        if (r && indWant.current.has(name)) drawIndicator(ch, name, r);
      }
      layoutPanes(ch);
      applyMarkers();
      publish();
    });
  };

  function drawIndicator(ch: IChartApi, name: IndicatorName, r: Record<string, Float64Array>) {
    const c = colors.current;
    const t = dataRef.current.t;
    const mine: ISeriesApi<SeriesType>[] = [];
    const pane = ch.panes().length; // at most one new pane per indicator
    const line = (vals: Float64Array, color: string, pn = 0, title = "") => {
      const ls = ch.addSeries(LineSeries, { color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, title }, pn);
      const pts = [];
      for (let i = 0; i < vals.length; i++) pts.push(Number.isFinite(vals[i]) ? { time: toTime(t[i]), value: vals[i] } : { time: toTime(t[i]) });
      ls.setData(pts);
      mine.push(ls);
      return ls;
    };
    if (r.SMA20) line(r.SMA20, c.acc, 0, "SMA20");
    if (r.SMA50) line(r.SMA50, c.warn, 0, "SMA50");
    if (r.EMA20) line(r.EMA20, c.fg, 0, "EMA20");
    // Longer averages. No up / down colours (those mean price direction); the series title tells SMA from EMA.
    if (r.SMA100) line(r.SMA100, c.val, 0, "SMA100");
    if (r.SMA200) line(r.SMA200, c.dim, 0, "SMA200");
    if (r.EMA50) line(r.EMA50, c.warn, 0, "EMA50");
    if (r.EMA200) line(r.EMA200, c.dim, 0, "EMA200");
    if (r.BB_MID) {
      line(r.BB_UP, c.dim, 0, "BB");
      line(r.BB_MID, c.dim, 0);
      line(r.BB_LO, c.dim, 0);
    }
    if (r.VWAP) line(r.VWAP, c.warn, 0, "VWAP");
    if (r.RSI) {
      const rs = line(r.RSI, c.acc, pane, "RSI14");
      rs.createPriceLine({ price: 70, color: c.line, lineWidth: 1, axisLabelVisible: false });
      rs.createPriceLine({ price: 30, color: c.line, lineWidth: 1, axisLabelVisible: false });
    }
    if (r.MACD) {
      const hist = ch.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false }, pane);
      const hp = [];
      for (let i = 0; i < r.MACD_HIST.length; i++) {
        const v = r.MACD_HIST[i];
        hp.push(Number.isFinite(v) ? { time: toTime(t[i]), value: v, color: v >= 0 ? c.up : c.down } : { time: toTime(t[i]) });
      }
      hist.setData(hp);
      mine.push(hist);
      line(r.MACD, c.acc, pane, "MACD");
      line(r.MACD_SIG, c.warn, pane);
    }
    // Phase 19 overlays on the price pane.
    const tri = (k: string, col: string, title: string) => {
      if (!r[k + "_UP"]) return;
      line(r[k + "_UP"], col, 0, title);
      line(r[k + "_MID"], col, 0);
      line(r[k + "_LO"], col, 0);
    };
    tri("KELT", c.dim, "KELT");
    tri("DONCH", c.dim, "DONCH");
    if (r.SUPERTREND) {
      const ls = ch.addSeries(LineSeries, { color: c.up, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, title: "SUPERTREND" }, 0);
      const pts = [];
      for (let i = 0; i < r.SUPERTREND.length; i++) {
        pts.push(Number.isFinite(r.SUPERTREND[i]) ? { time: toTime(t[i]), value: r.SUPERTREND[i], color: r.SUPERTREND_DIR[i] > 0 ? c.up : c.down } : { time: toTime(t[i]) });
      }
      ls.setData(pts);
      mine.push(ls);
    }
    if (r.PSAR) {
      const ls = ch.addSeries(LineSeries, { color: c.warn, lineVisible: false, pointMarkersVisible: true, pointMarkersRadius: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, title: "PSAR" }, 0);
      const pts = [];
      for (let i = 0; i < r.PSAR.length; i++) pts.push(Number.isFinite(r.PSAR[i]) ? { time: toTime(t[i]), value: r.PSAR[i] } : { time: toTime(t[i]) });
      ls.setData(pts);
      mine.push(ls);
    }
    if (r.ICHI_TENKAN) {
      line(r.ICHI_TENKAN, c.acc, 0, "TENKAN");
      line(r.ICHI_KIJUN, c.warn, 0, "KIJUN");
      line(r.ICHI_SPANA, c.up, 0, "SPAN A");
      line(r.ICHI_SPANB, c.down, 0, "SPAN B");
      line(r.ICHI_CHIKOU, c.dim, 0, "CHIKOU");
    }
    // Oscillators, one pane each.
    const osc = (vals: Float64Array | undefined, col: string, title: string, levels: number[] = []) => {
      if (!vals) return null;
      const ls = line(vals, col, pane, title);
      for (const price of levels) ls.createPriceLine({ price, color: c.line, lineWidth: 1, axisLabelVisible: false });
      return ls;
    };
    if (r.ATR) osc(r.ATR, c.acc, "ATR14");
    if (r.STOCH_K) { osc(r.STOCH_K, c.acc, "STOCH K", [80, 20]); line(r.STOCH_D, c.warn, pane); }
    if (r.ADX) { osc(r.ADX, c.fg, "ADX14", [25]); line(r.ADX_PDI, c.up, pane); line(r.ADX_MDI, c.down, pane); }
    if (r.OBV) osc(r.OBV, c.acc, "OBV");
    if (r.CCI) osc(r.CCI, c.acc, "CCI20", [100, -100]);
    if (r.WILLR) osc(r.WILLR, c.acc, "%R14", [-20, -80]);
    if (r.MFI) osc(r.MFI, c.acc, "MFI14", [80, 20]);

    // Pattern marks (rule-based, not signals) on the price series; SMC zones as dashed edges.
    const marks: SeriesMarker<Time>[] = [];
    if (r.PAT_CANDLE) {
      for (let i = 0; i < r.PAT_CANDLE.length; i++) {
        const info = PATTERN_INFO[r.PAT_CANDLE[i]];
        if (!info) continue;
        marks.push({ time: toTime(t[i]), position: info.dir < 0 ? "aboveBar" : "belowBar", shape: info.dir < 0 ? "arrowDown" : info.dir > 0 ? "arrowUp" : "circle", color: info.dir < 0 ? c.down : info.dir > 0 ? c.up : c.dim, text: info.short });
      }
    }
    if (r.SMC_SWING && r.SMC_BOS) {
      for (let i = 0; i < r.SMC_SWING.length; i++) {
        const sw = r.SMC_SWING[i];
        const b = r.SMC_BOS[i];
        if (sw) marks.push({ time: toTime(t[i]), position: sw > 0 ? "aboveBar" : "belowBar", shape: "circle", color: c.dim, size: 0.5 });
        if (b) marks.push({ time: toTime(t[i]), position: b > 0 ? "belowBar" : "aboveBar", shape: b > 0 ? "arrowUp" : "arrowDown", color: b > 0 ? c.up : c.down, text: Math.abs(b) === 2 ? "CHOCH" : "BOS" });
      }
      const z = r.SMC_ZONES ?? new Float64Array(0);
      for (let j = 0; j + 5 < z.length; j += 6) {
        const col = z[j] === 1 ? c.dim : z[j + 1] > 0 ? c.up : c.down;
        for (const price of [z[j + 4], z[j + 5]]) {
          const zs = ch.addSeries(LineSeries, { color: col, lineWidth: 1, lineStyle: LineStyle.Dashed, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, title: price === z[j + 4] ? (z[j] === 1 ? "FVG" : "OB") : "" }, 0);
          zs.setData([{ time: toTime(t[z[j + 2]]), value: price }, { time: toTime(t[z[j + 3]]), value: price }]);
          mine.push(zs);
        }
      }
    }
    ind.current.set(name, { series: mine, marks });
  }

  // Events changed: refresh the markers and the readout (its "[E ...]" suffix).
  useEffect(() => {
    if (!gp) return;
    applyMarkers();
    writeRef.current(cross.current.on ? cross.current.idx : dataRef.current.c.length - 1);
  // Runs only when the events change; everything else is read fresh through refs.
  // eslint-disable-next-line react-hooks/exhaustive-deps -- runs only when events change
  }, [events]);

  // The drawings overlay: repainted on pan / zoom / resize / crosshair move (rAF-coalesced, via core.paintRef) and when its inputs change.
  if (gp) {
    paintRef.current = () => {
      const cv = overlay.current;
      const chart = chartRef.current;
      const s = main.current;
      const host = box.current;
      if (!cv || !chart || !s || !host) return;
      const w = host.clientWidth;
      const h = host.clientHeight;
      const dpr = window.devicePixelRatio || 1;
      if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) {
        cv.width = Math.round(w * dpr);
        cv.height = Math.round(h * dpr);
      }
      const ctx = cv.getContext("2d");
      if (!ctx) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      const d = drawRef.current;
      const bars = dataRef.current;
      const plotW = Math.max(0, w - chart.priceScale("right").width());
      const ts = chart.timeScale();
      const geo: Geo = {
        toX: (t) => ts.logicalToCoordinate(timeToLogical(t, bars.t) as Logical),
        toY: (p) => s.priceToCoordinate(p),
        width: plotW,
      };
      geoRef.current = geo;
      if (!d || compareOn.current || (!d.drawings.length && !d.pending)) {
        gauges.set("chart.drawSegs", 0);
        return;
      }
      const c = colors.current;
      ctx.save();
      ctx.beginPath();
      ctx.rect(0, 0, plotW, chart.panes()[0]?.getHeight() ?? h);
      ctx.clip();
      ctx.font = `${c.fs}px ${c.font}`;
      ctx.lineWidth = 1;
      let nSegs = 0;
      const stroke = (list: Drawing[], color: (id: string) => string, dash: number[]) => {
        for (const dr of list) {
          const col = color(dr.id);
          ctx.strokeStyle = col;
          ctx.fillStyle = col;
          ctx.setLineDash(dr.kind === "FIB" ? [] : dash);
          for (const sg of segments(dr, geo)) {
            nSegs++;
            ctx.setLineDash(!sg.label && dr.kind === "FIB" ? [3, 3] : dr.kind === "FIB" ? [] : dash);
            ctx.beginPath();
            ctx.moveTo(sg.x1, sg.y1);
            ctx.lineTo(sg.x2, sg.y2);
            ctx.stroke();
            const text = sg.label ? `${sg.label} ${fmtPrice(sg.price ?? NaN)}` : sg.price !== undefined ? fmtPrice(sg.price) : "";
            if (text) ctx.fillText(text, Math.max(2, sg.x2 - ctx.measureText(text).width - 4), sg.y1 - 2);
          }
        }
      };
      stroke(d.drawings, (id) => (id === d.selected ? c.warn : c.fg), []);
      if (d.pending) {
        const i = cross.current.on ? cross.current.idx : -1;
        const pts = [...d.pending.pts];
        if (i >= 0 && i < bars.t.length && pts.length < (d.pending.kind === "HLINE" ? 1 : 2)) {
          const px = d.pending.anchor === "H" ? bars.h[i] : d.pending.anchor === "L" ? bars.l[i] : d.pending.anchor === "O" ? bars.o[i] : bars.c[i];
          pts.push({ t: bars.t[i], p: px });
        }
        stroke([{ id: "pending", kind: d.pending.kind, pts }], () => c.acc, [4, 3]);
      }
      ctx.restore();
      gauges.set("chart.drawSegs", nSegs);
    };
  }
  useEffect(() => {
    if (!gp) return;
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = 0;
      paintRef.current();
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps -- repaint when the drawings or the chart's inputs change
  }, [draw, data, indicators, comparePanes, compare, ver]);

  return { overlay };
}
