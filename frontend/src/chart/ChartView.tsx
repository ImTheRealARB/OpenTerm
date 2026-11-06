/**
 * Price chart core used by GP (and PERF CHART for load tests). Canvas rendering via TradingView
 * Lightweight Charts (Apache-2.0, attribution shown in GP's status line and README).
 * Indicators run in a Web Worker; live ticks update the last bar in place.
 */
import "../components/dataColors.css";
import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import {
  AreaSeries, BarSeries, BaselineSeries, CandlestickSeries, ColorType, CrosshairMode, HistogramSeries, LineSeries, LineStyle,
  PriceScaleMode, TickMarkType, createChart, createSeriesMarkers,
  type IChartApi, type ISeriesApi, type ISeriesMarkersPluginApi, type Logical, type SeriesMarker, type SeriesType, type Time, type UTCTimestamp,
} from "lightweight-charts";
import { fmtBig, fmtPrice } from "../format";
import { gauges } from "../perf/metrics";
import { displayVersion } from "../settings/runtime";
import { useStore } from "../state/store";
import type { IndicatorName } from "./indicators";
import { diffIndicators } from "./indicatorDiff";
import { hitTest, segments, timeToLogical, type DPoint, type DrawKind, type Drawing, type Geo } from "./drawings";
import { PATTERN_INFO } from "./patterns";
import type { LibraryRes } from "./libraryWorker";

import { CHART_TYPES, isOhlcType, type ChartType } from "./chartTypes";
import { heikinAshi } from "./heikin";

export { CHART_TYPES };
export type { ChartType };

export interface BarData {
  symbol: string;
  interval: string;
  tz: string;
  t: Float64Array; // epoch seconds
  o: Float64Array;
  h: Float64Array;
  l: Float64Array;
  c: Float64Array;
  v: Float64Array;
}

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

export interface ChartHandle {
  /** Bar index under the keyboard crosshair (the last bar when it is off). */
  crosshairIndex(): number;
  pan(bars: number): void;
  zoom(factor: number): void;
  crosshair(on: boolean): void;
  crosshairStep(delta: number): void;
  live(price: number, timeMs: number, dayVolume: number | null): void;
  /** Price an alert key should use: the keyboard crosshair bar's close when it is on, else the last price (null before any bar). */
  alertPrice(): number | null;
  /** The last price (live ticks included), or null. */
  lastPrice(): number | null;
  /** PNG data URL of the chart as drawn (for AI CHART), or null. */
  screenshot(): string | null;
}

interface Props {
  data: BarData;
  compare?: { symbol: string; t: Float64Array; c: Float64Array } | null;
  type: ChartType;
  log: boolean;
  indicators: IndicatorName[];
  /** Single-value series (FRED): the readout shows `<date> <label> <value>` instead of O/H/L/C/V. */
  readoutLabel?: string;
  /** BT: one extra line in a second pane on the same timestamps as `data` (drawdown). NaN = gap. */
  lowerPane?: { title: string; v: Float64Array } | null;
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

/** One library indicator (`id` + `params`) or formula on the chart. `key` is stable (`LIB:ATR:14`, `F:<encoded formula>`); `label` titles its series. */
export interface CustomItem {
  key: string;
  label: string;
  id?: string;
  params?: number[];
  formula?: string;
}

export const INTERVAL_S: Record<string, number> = {
  "1s": 1, "5s": 5, "15s": 15, "1m": 60, "2m": 120, "5m": 300, "15m": 900, "30m": 1800, "60m": 3600, "90m": 5400,
  "1d": 86400, "1wk": 7 * 86400, "1mo": 31 * 86400,
};

function themeColors() {
  const cs = getComputedStyle(document.documentElement);
  const v = (n: string) => cs.getPropertyValue(n).trim();
  return { bg: v("--bg"), fg: v("--fg"), dim: v("--fg-dim"), up: v("--up"), down: v("--down"), line: v("--line"), acc: v("--accent"), warn: v("--warn"), sel: v("--sel"), val: v("--val") || v("--fg"), bar: v("--bar") || v("--sel"), grid: v("--chart-grid") || v("--bar") || v("--line"), cup: v("--chart-up") || v("--up"), cdown: v("--chart-down") || v("--down"), cline: v("--chart-line") || v("--val") || v("--fg"), font: v("--font"), fs: Math.round(parseFloat(v("--fs")) - 1) || 11 };
}

const toTime = (s: number) => s as UTCTimestamp;

function formatters(tz: string, intraday: boolean, seconds = false) {
  const opts = { timeZone: tz } as const;
  const sec = seconds ? ({ second: "2-digit" } as const) : {};
  const time = new Intl.DateTimeFormat("en-GB", { ...opts, hour: "2-digit", minute: "2-digit", ...sec, hourCycle: "h23" });
  const day = new Intl.DateTimeFormat("en-GB", { ...opts, day: "2-digit", month: "short" });
  const month = new Intl.DateTimeFormat("en-GB", { ...opts, month: "short" });
  const year = new Intl.DateTimeFormat("en-GB", { ...opts, year: "numeric" });
  const full = new Intl.DateTimeFormat("en-GB", { ...opts, day: "2-digit", month: "short", year: "numeric", ...(intraday ? { hour: "2-digit", minute: "2-digit", ...sec, hourCycle: "h23" } : {}) });
  const ms = (t: Time) => (t as number) * 1000;
  return {
    tick: (t: Time, type: TickMarkType) =>
      type === TickMarkType.Year ? year.format(ms(t)) : type === TickMarkType.Month ? month.format(ms(t)) : type === TickMarkType.DayOfMonth ? day.format(ms(t)) : time.format(ms(t)),
    full: (t: Time) => full.format(ms(t)).toUpperCase(),
  };
}

function ChartViewInner({ data, compare, type, log, indicators, readoutLabel, lowerPane, comparePanes, draw, events, onPick, alertLevels, onPickPrice, pickArmed, custom, onCustomErrors }: Props, ref: React.Ref<ChartHandle>) {
  const box = useRef<HTMLDivElement>(null);
  const readout = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  // lightweight-charts queues scroll and zoom requests and applies them on its next paint, so
  // getVisibleLogicalRange() keeps returning the old range until then. Keys pressed faster than a
  // frame (key repeat, a fast machine, Playwright) would each start from that stale range and all
  // but the last would be lost. pan()/zoom() build on the range they last requested instead; it is
  // forgotten one frame later, once the chart has applied it.
  const pendingRange = useRef<{ from: number; to: number } | null>(null);
  const main = useRef<ISeriesApi<SeriesType> | null>(null);
  const vol = useRef<ISeriesApi<"Histogram"> | null>(null);
  const extra = useRef<ISeriesApi<SeriesType>[]>([]);
  const last = useRef<{ t: number; o: number; h: number; l: number; c: number; v: number } | null>(null);
  const cross = useRef({ on: false, idx: -1 });
  const hovering = useRef(false); // the mouse crosshair is over the chart
  const fmt = useRef(formatters(data.tz, (INTERVAL_S[data.interval] ?? 86400) < 86400, (INTERVAL_S[data.interval] ?? 86400) < 60));
  const worker = useRef<Worker | null>(null);
  const reqId = useRef(0);
  // Phase 19 refs: the overlay canvas, the marker plugin of the price series, the latest props the overlay paints from.
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
  const customRef = useRef<CustomItem[]>(custom ?? []);
  customRef.current = custom ?? [];
  const errCb = useRef(onCustomErrors);
  errCb.current = onCustomErrors;
  const onLibResult = useRef<(m: LibraryRes) => void>(() => {});
  const basePanes = useRef(1);
  const onIndResult = useRef<(id: number, parts: Partial<Record<IndicatorName, Record<string, Float64Array>>>) => void>(() => {});
  const eventsRef = useRef<ChartMarkerEvent[] | undefined>(events);
  eventsRef.current = events;
  const drawRef = useRef<DrawState | undefined>(draw);
  drawRef.current = draw;
  const dataRef = useRef(data);
  dataRef.current = data;
  const pickRef = useRef({ armed: false, cb: onPickPrice });
  pickRef.current = { armed: !!pickArmed, cb: onPickPrice };
  const compareOn = useRef(false);
  compareOn.current = !!compare;
  const geoRef = useRef<Geo | null>(null);
  const writeRef = useRef<(i: number) => void>(() => {});
  const paintRef = useRef<() => void>(() => {});
  const rafRef = useRef(0);

  const colors = useRef(themeColors());
  // Phase 10: theme switch. Colours are re-read once per change (never per frame), then series are rebuilt.
  const ver = useStore(displayVersion, (v) => v);
  const seenVer = useRef(ver);

  const writeReadout = (i: number) => {
    const el = readout.current;
    if (!el || i < 0 || i >= data.c.length) return;
    // The newest bar follows live ticks: `last` holds its running values (`data` is the history snapshot).
    // A new intraday bucket (last.t is later than the final history bar) is measured against that final bar's close.
    const lv = !compare && i === data.c.length - 1 ? last.current : null;
    const bar = lv ?? { t: data.t[i], o: data.o[i], h: data.h[i], l: data.l[i], c: data.c[i], v: data.v[i] };
    const prev = lv && lv.t !== data.t[i] ? data.c[i] : i > 0 ? data.c[i - 1] : NaN;
    const chg = Number.isFinite(prev) ? ((bar.c - prev) / prev) * 100 : NaN;
    if (readoutLabel) {
      el.textContent = `${fmt.current.full(toTime(bar.t))}  ${readoutLabel} ${fmtPrice(bar.c)}` + (Number.isFinite(chg) ? `  ${chg >= 0 ? "+" : ""}${chg.toFixed(2)}%` : "");
      el.className = "line " + (chg > 0 ? "up" : chg < 0 ? "down" : "");
      return;
    }
    el.textContent =
      `${fmt.current.full(toTime(bar.t))}  O ${fmtPrice(bar.o)}  H ${fmtPrice(bar.h)}  L ${fmtPrice(bar.l)}  ` +
      `C ${fmtPrice(bar.c)}  V ${fmtBig(bar.v)}` + (Number.isFinite(chg) ? `  ${chg >= 0 ? "+" : ""}${chg.toFixed(2)}%` : "") +
      eventText(i);
    el.className = "line " + (chg > 0 ? "up" : chg < 0 ? "down" : "");
  };
  writeRef.current = writeReadout;
  const eventText = (i: number) => {
    const t = data.t[i];
    const hit = (events ?? []).filter((e) => e.t === t);
    return hit.length ? "  [" + hit.map((e) => e.detail).join(" | ") + "]" : "";
  };

  // Chart instance: created once per panel.
  useEffect(() => {
    const c = colors.current;
    const chart = createChart(box.current!, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: c.bg }, textColor: c.dim, fontFamily: c.font, fontSize: c.fs, attributionLogo: false, panes: { separatorColor: c.line, enableResize: false } },
      grid: { vertLines: { color: c.grid }, horzLines: { color: c.grid } },
      rightPriceScale: { borderColor: c.line },
      timeScale: { borderColor: c.line, timeVisible: (INTERVAL_S[data.interval] ?? 86400) < 86400, secondsVisible: false, rightOffset: 3, lockVisibleTimeRangeOnResize: true },
      crosshair: { mode: CrosshairMode.Normal, vertLine: { color: c.dim, labelBackgroundColor: c.sel }, horzLine: { color: c.dim, labelBackgroundColor: c.sel } },
      kineticScroll: { mouse: false, touch: false },
      localization: { timeFormatter: (t: Time) => fmt.current.full(t) },
    });
    chart.subscribeCrosshairMove((p) => {
      hovering.current = p.logical != null; // a live tick must not pull the readout off the bar under the mouse
      if (p.logical == null) return;
      writeRef.current(Math.round(p.logical as number));
    });
    const schedule = () => {
      if (rafRef.current) return;
      rafRef.current = requestAnimationFrame(() => {
        rafRef.current = 0;
        const vr = chart.timeScale().getVisibleLogicalRange();
        if (vr) {
          gauges.set("chart.visFrom", vr.from);
          gauges.set("chart.visTo", vr.to);
        }
        paintRef.current();
      });
    };
    chart.timeScale().subscribeVisibleLogicalRangeChange(schedule);
    chart.subscribeCrosshairMove(schedule);
    const ro = new ResizeObserver(schedule);
    ro.observe(box.current!);
    chartRef.current = chart;
    return () => {
      worker.current?.terminate();
      worker.current = null;
      ro.disconnect();
      cancelAnimationFrame(rafRef.current);
      rafRef.current = 0;
      chart.remove();
      chartRef.current = null;
    };
  // Created once per panel. data.interval only seeds timeVisible here; the data effect re-applies it on interval change.
  // eslint-disable-next-line react-hooks/exhaustive-deps -- chart is created once; later interval changes are applied via applyOptions in the data effect
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || seenVer.current === ver) return;
    seenVer.current = ver;
    const c = (colors.current = themeColors());
    chart.applyOptions({
      layout: { background: { type: ColorType.Solid, color: c.bg }, textColor: c.dim, fontSize: c.fs, panes: { separatorColor: c.line } },
      grid: { vertLines: { color: c.grid }, horzLines: { color: c.grid } },
      rightPriceScale: { borderColor: c.line },
      timeScale: { borderColor: c.line },
      crosshair: { vertLine: { color: c.dim, labelBackgroundColor: c.sel }, horzLine: { color: c.dim, labelBackgroundColor: c.sel } },
    });
  }, [ver]);

  // Series + data: rebuilt when data, type, log, compare, indicators or the theme change (not on ticks).
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const c = colors.current;
    fmt.current = formatters(data.tz, (INTERVAL_S[data.interval] ?? 86400) < 86400, (INTERVAL_S[data.interval] ?? 86400) < 60);
    chart.applyOptions({
      timeScale: { timeVisible: (INTERVAL_S[data.interval] ?? 86400) < 86400, secondsVisible: (INTERVAL_S[data.interval] ?? 86400) < 60, tickMarkFormatter: fmt.current.tick },
    });
    for (const s of [main.current, vol.current, ...extra.current, ...[...ind.current.values()].flatMap((e) => e.series), ...[...lib.current.values()].flat()]) if (s) chart.removeSeries(s);
    extra.current = [];
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
    main.current = null;
    vol.current = null;

    const n = data.c.length;
    const kind: ChartType = compare ? "LINE" : type;
    let s: ISeriesApi<SeriesType>;
    if (isOhlcType(kind)) {
      // Heikin Ashi draws smoothed bars (heikin.ts); every other OHLC type draws the real ones.
      const src = kind === "HEIKIN" ? heikinAshi(data.o, data.h, data.l, data.c) : data;
      const ohlc = new Array(n);
      for (let i = 0; i < n; i++) ohlc[i] = { time: toTime(data.t[i]), open: src.o[i], high: src.h[i], low: src.l[i], close: src.c[i] };
      s = kind === "OHLC"
        ? chart.addSeries(BarSeries, { upColor: c.cup, downColor: c.cdown, thinBars: true })
        : kind === "HOLLOW"
          // Hollow candles: rising bodies are empty outlines, falling ones are filled.
          ? chart.addSeries(CandlestickSeries, { upColor: "rgba(0,0,0,0)", downColor: c.cdown, borderUpColor: c.cup, borderDownColor: c.cdown, wickUpColor: c.cup, wickDownColor: c.cdown, borderVisible: true })
          : chart.addSeries(CandlestickSeries, { upColor: c.cup, downColor: c.cdown, wickUpColor: c.cup, wickDownColor: c.cdown, borderVisible: false });
      s.setData(ohlc);
    } else {
      const pts = new Array(n);
      for (let i = 0; i < n; i++) pts[i] = { time: toTime(data.t[i]), value: data.c[i] };
      // Baseline: green above the first close of the range, red below it.
      const base = n ? data.c[0] : 0;
      s = kind === "AREA"
        ? chart.addSeries(AreaSeries, { lineColor: c.cline, topColor: c.sel, bottomColor: c.bg, lineWidth: 1 })
        : kind === "BASELINE"
          ? chart.addSeries(BaselineSeries, { baseValue: { type: "price", price: base }, lineWidth: 1, topLineColor: c.cup, bottomLineColor: c.cdown, topFillColor1: c.cup + "55", topFillColor2: c.cup + "05", bottomFillColor1: c.cdown + "05", bottomFillColor2: c.cdown + "55" })
          : chart.addSeries(LineSeries, { color: c.cline, lineWidth: 1 });
      s.setData(pts);
    }
    main.current = s;
    markersApi.current = createSeriesMarkers(s, []);
    applyMarkers();
    last.current = n ? { t: data.t[n - 1], o: data.o[n - 1], h: data.h[n - 1], l: data.l[n - 1], c: data.c[n - 1], v: data.v[n - 1] } : null;

    // Series without volume (FRED, indices on some feeds) get no histogram: zero bars draw as a flat line.
    let hasVolume = false;
    for (let i = 0; i < n && !hasVolume; i++) hasVolume = data.v[i] > 0;
    if (!compare && hasVolume) {
      const v = chart.addSeries(HistogramSeries, { priceScaleId: "vol", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false });
      chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
      const bars = new Array(n);
      for (let i = 0; i < n; i++) bars[i] = { time: toTime(data.t[i]), value: Number.isFinite(data.v[i]) ? data.v[i] : 0, color: data.c[i] >= data.o[i] ? c.up : c.down };
      v.setData(bars);
      vol.current = v;
    } else if (compare) {
      const cs = chart.addSeries(LineSeries, { color: c.acc, lineWidth: 1, title: compare.symbol });
      const pts = [];
      for (let i = 0; i < compare.t.length; i++) if (Number.isFinite(compare.c[i])) pts.push({ time: toTime(compare.t[i]), value: compare.c[i] });
      cs.setData(pts);
      extra.current.push(cs);
    }
    if (lowerPane) {
      const ls = chart.addSeries(LineSeries, { color: c.down, lineWidth: 1, priceLineVisible: false, title: lowerPane.title, priceFormat: { type: "percent" } }, 1);
      const pts = [];
      for (let i = 0; i < Math.min(n, lowerPane.v.length); i++) pts.push(Number.isFinite(lowerPane.v[i]) ? { time: toTime(data.t[i]), value: lowerPane.v[i] } : { time: toTime(data.t[i]) });
      ls.setData(pts);
      extra.current.push(ls);
      chart.panes()[1]?.setHeight(90);
    }
    (comparePanes ?? []).forEach((cp, k) => {
      const pane = 1 + k + (lowerPane ? 1 : 0);
      const ls = chart.addSeries(LineSeries, { color: c.acc, lineWidth: 1, priceLineVisible: false, title: cp.symbol }, pane);
      const pts = [];
      for (let i = 0; i < cp.t.length; i++) if (Number.isFinite(cp.c[i])) pts.push({ time: toTime(cp.t[i]), value: cp.c[i] });
      ls.setData(pts);
      extra.current.push(ls);
      chart.panes()[pane]?.setHeight(110);
    });
    chart.priceScale("right").applyOptions({
      mode: compare ? PriceScaleMode.Percentage : log ? PriceScaleMode.Logarithmic : PriceScaleMode.Normal,
    });
    chart.timeScale().fitContent();
    writeReadout(n - 1);

    basePanes.current = 1 + (comparePanes?.length ?? 0) + (lowerPane ? 1 : 0);
    gauges.set("chart.rebuilds", (gauges.get("chart.rebuilds") ?? 0) + 1);
    publish();
  // Rebuilding the chart is expensive: it must happen only for these inputs, never because writeReadout is a new function each render.
  // eslint-disable-next-line react-hooks/exhaustive-deps -- rebuild only on data/compare/type/log/panes/theme; writeReadout is re-created every render
  }, [data, compare, type, log, lowerPane, comparePanes, ver]);

  // Alert lines: dashed "ALRT" price lines on the price series. Re-created after a rebuild (the series is new); a level change
  // touches only these lines, never the series, so zoom and the indicator toggles stay untouched.
  const levelsKey = (alertLevels ?? []).join(",");
  useEffect(() => {
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
  }, [levelsKey, data, compare, type, log, lowerPane, comparePanes, ver]);

  function publish() {
    let n = extra.current.length;
    for (const e of ind.current.values()) n += e.series.length;
    for (const s of lib.current.values()) n += s.length;
    gauges.set("chart.extraSeries", n);
    gauges.set("chart.panes", chartRef.current?.panes().length ?? 0);
  }

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

  // Indicators: a toggle adds or removes only that indicator's series (and its pane); zoom and scroll stay.
  // Runs after the series effect above, which clears `indWant` whenever it rebuilds, so a rebuild re-adds them all.
  useEffect(() => {
    const ch = chartRef.current;
    if (!ch) return;
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
      // Started on the first indicator request: line-only charts (FRED, BT) never pay for the worker.
      ensureWorker();
      // ONE message for the whole batch: the six bar arrays are copied once, not once per indicator.
      const id = ++reqId.current;
      indReq.current.set(id, add);
      for (const name of add) indWant.current.add(name);
      // Copies: the worker gets its own buffers so `data` stays usable here.
      ensureWorker().postMessage({ id, which: add, series: { t: data.t.slice(), o: data.o.slice(), h: data.h.slice(), l: data.l.slice(), c: data.c.slice(), v: data.v.slice() } });
    }
  }, [indicators, data, compare, type, log, lowerPane, comparePanes, ver]);

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

  // Library / formula indicators: the same add/remove-only-this-entry rule, one worker request for a batch of adds.
  const customKey = (custom ?? []).map((x) => x.key).join("\n");
  useEffect(() => {
    const ch = chartRef.current;
    if (!ch) return;
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
  useEffect(() => {
    applyMarkers();
    writeReadout(cross.current.on ? cross.current.idx : data.c.length - 1);
  // writeReadout is this render's closure, so it sees fresh data; re-running only on events is the point (markers + readout refresh).
  // eslint-disable-next-line react-hooks/exhaustive-deps -- runs only when events change; writeReadout/data are read fresh from this render
  }, [events]);

  // The drawings overlay: repainted on pan / zoom / resize / crosshair move (rAF-coalesced) and when its inputs change.
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
  useEffect(() => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = 0;
      paintRef.current();
    });
  }, [draw, data, indicators, comparePanes, compare, ver]);

  // Ask the chart for a new visible range and remember it until the chart has painted it (see pendingRange).
  const requestRange = (ts: ReturnType<IChartApi["timeScale"]>, r: { from: number; to: number }) => {
    if (!pendingRange.current) requestAnimationFrame(() => (pendingRange.current = null));
    pendingRange.current = r;
    ts.setVisibleLogicalRange(r);
  };

  useImperativeHandle(ref, () => ({
    crosshairIndex() {
      return cross.current.on ? cross.current.idx : data.c.length - 1;
    },
    screenshot() {
      try {
        return chartRef.current?.takeScreenshot().toDataURL("image/png") ?? null;
      } catch {
        return null;
      }
    },
    pan(bars) {
      // Shift the whole range by `bars`: same width, so the bar spacing (zoom) is unchanged.
      const ts = chartRef.current?.timeScale();
      const r = pendingRange.current ?? ts?.getVisibleLogicalRange();
      if (!ts || !r) return;
      requestRange(ts, { from: r.from + bars, to: r.to + bars });
    },
    zoom(factor) {
      // Keep the right edge fixed and scale the width (factor < 1 zooms in).
      const ts = chartRef.current?.timeScale();
      const r = pendingRange.current ?? ts?.getVisibleLogicalRange();
      if (!ts || !r) return;
      const width = Math.max(10, (r.to - r.from) * factor);
      requestRange(ts, { from: r.to - width, to: r.to });
    },
    crosshair(on) {
      cross.current.on = on;
      const chart = chartRef.current;
      if (!chart || !main.current) return;
      if (!on) {
        chart.clearCrosshairPosition();
        writeReadout(data.c.length - 1);
        return;
      }
      cross.current.idx = data.c.length - 1;
      this.crosshairStep(0);
    },
    crosshairStep(delta) {
      const chart = chartRef.current;
      if (!chart || !main.current || !cross.current.on) return;
      const i = Math.max(0, Math.min(data.c.length - 1, cross.current.idx + delta));
      cross.current.idx = i;
      chart.setCrosshairPosition(data.c[i], toTime(data.t[i]), main.current);
      writeReadout(i);
    },
    lastPrice() {
      return last.current && Number.isFinite(last.current.c) ? last.current.c : null;
    },
    alertPrice() {
      const px = cross.current.on ? data.c[cross.current.idx] : last.current?.c;
      return px !== undefined && Number.isFinite(px) ? px : null;
    },
    live(price, timeMs, dayVolume) {
      const s = main.current;
      const b = last.current;
      if (!s || !b || compare || type === "HEIKIN") return; // Heikin Ashi bars chain from the previous bar: they refresh with the next history load
      const iv = INTERVAL_S[data.interval] ?? 86400;
      const ts = Math.floor(timeMs / 1000);
      if (ts < b.t) return;
      if (ts < b.t + iv) {
        // Same bar: extend it.
        b.c = price;
        b.h = Math.max(b.h, price);
        b.l = Math.min(b.l, price);
        if (iv >= 86400 && dayVolume != null) b.v = dayVolume;
      } else if (iv < 86400) {
        // New intraday bucket, aligned to the interval grid.
        const t = b.t + Math.floor((ts - b.t) / iv) * iv;
        Object.assign(b, { t, o: price, h: price, l: price, c: price, v: 0 });
      } else {
        return; // new daily+ bar: arrives with the next history refresh rather than guessed here
      }
      const time = toTime(b.t);
      if (isOhlcType(type)) s.update({ time, open: b.o, high: b.h, low: b.l, close: b.c });
      else s.update({ time, value: b.c });
      // The volume bar under the candle follows too (same up / down colour rule as at build time).
      // A new intraday bucket gets its own bar; its volume is 0 until the next history load.
      const cols = colors.current;
      vol.current?.update({ time, value: Number.isFinite(b.v) ? b.v : 0, color: b.c >= b.o ? cols.up : cols.down });
      // Keep the readout current, unless a crosshair (keyboard or mouse) is parked on a bar: that bar's values must not jump.
      if (!cross.current.on && !hovering.current) writeRef.current(dataRef.current.c.length - 1);
    },
  }));

  return (
    <div className="fn">
      <div ref={readout} className="line" />
      <div
        ref={box}
        className="chart"
        onClick={(e) => {
          const pk = pickRef.current;
          if (pk.cb && (pk.armed || e.altKey) && main.current && !compareOn.current) {
            const r = e.currentTarget.getBoundingClientRect();
            const px = main.current.coordinateToPrice(e.clientY - r.top);
            pk.cb(px === null ? NaN : (px as number));
            return;
          }
          const g = geoRef.current;
          const d = drawRef.current;
          if (!g || !d || !onPick || compareOn.current) return;
          const r = e.currentTarget.getBoundingClientRect();
          onPick(hitTest(d.drawings, e.clientX - r.left, e.clientY - r.top, g, 6));
        }}
      >
        <canvas ref={overlay} style={{ position: "absolute", left: 0, top: 0, width: "100%", height: "100%", pointerEvents: "none", zIndex: 3 }} />
      </div>
    </div>
  );
}

export const ChartView = forwardRef(ChartViewInner);
export default ChartView;

/** Converts the API's nullable columns to Float64Arrays, dropping bars without a close. */
export function toBarData(b: { symbol: string; interval: string; tz: string | null; t: number[]; o: (number | null)[]; h: (number | null)[]; l: (number | null)[]; c: (number | null)[]; v: (number | null)[] }): BarData {
  const keep: number[] = [];
  for (let i = 0; i < b.t.length; i++) if (b.c[i] != null) keep.push(i);
  const col = (a: (number | null)[], fallback?: (number | null)[]) =>
    Float64Array.from(keep, (i) => a[i] ?? fallback?.[i] ?? NaN);
  return {
    symbol: b.symbol, interval: b.interval, tz: b.tz ?? "UTC",
    t: Float64Array.from(keep, (i) => b.t[i]), o: col(b.o, b.c), h: col(b.h, b.c), l: col(b.l, b.c), c: col(b.c), v: col(b.v),
  };
}
