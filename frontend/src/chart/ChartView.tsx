/**
 * Price chart core used by GP (and PERF CHART for load tests). Canvas rendering via TradingView
 * Lightweight Charts (Apache-2.0, attribution shown in GP's status line and README).
 * Indicators run in a Web Worker; live ticks update the last bar in place.
 */
import "../components/dataColors.css";
import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import {
  AreaSeries, BarSeries, CandlestickSeries, ColorType, CrosshairMode, HistogramSeries, LineSeries, LineStyle,
  PriceScaleMode, TickMarkType, createChart, createSeriesMarkers,
  type IChartApi, type ISeriesApi, type ISeriesMarkersPluginApi, type Logical, type SeriesMarker, type SeriesType, type Time, type UTCTimestamp,
} from "lightweight-charts";
import { fmtBig, fmtPrice } from "../format";
import { gauges } from "../perf/metrics";
import { displayVersion } from "../settings/runtime";
import { useStore } from "../state/store";
import type { IndicatorName } from "./indicators";
import { hitTest, segments, timeToLogical, type DPoint, type DrawKind, type Drawing, type Geo } from "./drawings";
import { PATTERN_INFO } from "./patterns";

import { CHART_TYPES, type ChartType } from "./chartTypes";

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
}

export const INTERVAL_S: Record<string, number> = {
  "1s": 1, "5s": 5, "15s": 15, "1m": 60, "2m": 120, "5m": 300, "15m": 900, "30m": 1800, "60m": 3600, "90m": 5400,
  "1d": 86400, "1wk": 7 * 86400, "1mo": 31 * 86400,
};

function themeColors() {
  const cs = getComputedStyle(document.documentElement);
  const v = (n: string) => cs.getPropertyValue(n).trim();
  return { bg: v("--bg"), fg: v("--fg"), dim: v("--fg-dim"), up: v("--up"), down: v("--down"), line: v("--line"), acc: v("--accent"), warn: v("--warn"), sel: v("--sel"), val: v("--val") || v("--fg"), bar: v("--bar") || v("--sel"), grid: v("--chart-grid") || v("--bar") || v("--line"), cup: v("--chart-up") || v("--up"), cdown: v("--chart-down") || v("--down"), cline: v("--chart-line") || v("--val") || v("--fg"), font: v("--font") };
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

function ChartViewInner({ data, compare, type, log, indicators, readoutLabel, lowerPane, comparePanes, draw, events, onPick }: Props, ref: React.Ref<ChartHandle>) {
  const box = useRef<HTMLDivElement>(null);
  const readout = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const main = useRef<ISeriesApi<SeriesType> | null>(null);
  const vol = useRef<ISeriesApi<"Histogram"> | null>(null);
  const extra = useRef<ISeriesApi<SeriesType>[]>([]);
  const last = useRef<{ t: number; o: number; h: number; l: number; c: number; v: number } | null>(null);
  const cross = useRef({ on: false, idx: -1 });
  const fmt = useRef(formatters(data.tz, (INTERVAL_S[data.interval] ?? 86400) < 86400, (INTERVAL_S[data.interval] ?? 86400) < 60));
  const worker = useRef<Worker | null>(null);
  const reqId = useRef(0);
  // Phase 19 refs: the overlay canvas, the marker plugin of the price series, the latest props the overlay paints from.
  const overlay = useRef<HTMLCanvasElement>(null);
  const markersApi = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const patMarks = useRef<SeriesMarker<Time>[]>([]);
  const eventsRef = useRef<ChartMarkerEvent[] | undefined>(events);
  eventsRef.current = events;
  const drawRef = useRef<DrawState | undefined>(draw);
  drawRef.current = draw;
  const dataRef = useRef(data);
  dataRef.current = data;
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
    const prev = i > 0 ? data.c[i - 1] : NaN;
    const chg = Number.isFinite(prev) ? ((data.c[i] - prev) / prev) * 100 : NaN;
    if (readoutLabel) {
      el.textContent = `${fmt.current.full(toTime(data.t[i]))}  ${readoutLabel} ${fmtPrice(data.c[i])}` + (Number.isFinite(chg) ? `  ${chg >= 0 ? "+" : ""}${chg.toFixed(2)}%` : "");
      el.className = "line " + (chg > 0 ? "up" : chg < 0 ? "down" : "");
      return;
    }
    el.textContent =
      `${fmt.current.full(toTime(data.t[i]))}  O ${fmtPrice(data.o[i])}  H ${fmtPrice(data.h[i])}  L ${fmtPrice(data.l[i])}  ` +
      `C ${fmtPrice(data.c[i])}  V ${fmtBig(data.v[i])}` + (Number.isFinite(chg) ? `  ${chg >= 0 ? "+" : ""}${chg.toFixed(2)}%` : "") +
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
      layout: { background: { type: ColorType.Solid, color: c.bg }, textColor: c.dim, fontFamily: c.font, fontSize: 11, attributionLogo: false, panes: { separatorColor: c.line, enableResize: false } },
      grid: { vertLines: { color: c.grid }, horzLines: { color: c.grid } },
      rightPriceScale: { borderColor: c.line },
      timeScale: { borderColor: c.line, timeVisible: (INTERVAL_S[data.interval] ?? 86400) < 86400, secondsVisible: false, rightOffset: 3 },
      crosshair: { mode: CrosshairMode.Normal, vertLine: { color: c.dim, labelBackgroundColor: c.sel }, horzLine: { color: c.dim, labelBackgroundColor: c.sel } },
      kineticScroll: { mouse: false, touch: false },
      localization: { timeFormatter: (t: Time) => fmt.current.full(t) },
    });
    chart.subscribeCrosshairMove((p) => {
      if (p.logical == null) return;
      writeRef.current(Math.round(p.logical as number));
    });
    const schedule = () => {
      if (rafRef.current) return;
      rafRef.current = requestAnimationFrame(() => {
        rafRef.current = 0;
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
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || seenVer.current === ver) return;
    seenVer.current = ver;
    const c = (colors.current = themeColors());
    chart.applyOptions({
      layout: { background: { type: ColorType.Solid, color: c.bg }, textColor: c.dim, panes: { separatorColor: c.line } },
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
    for (const s of [main.current, vol.current, ...extra.current]) if (s) chart.removeSeries(s);
    extra.current = [];
    main.current = null;
    vol.current = null;

    const n = data.c.length;
    const kind: ChartType = compare ? "LINE" : type;
    let s: ISeriesApi<SeriesType>;
    if (kind === "CANDLE" || kind === "OHLC") {
      const ohlc = new Array(n);
      for (let i = 0; i < n; i++) ohlc[i] = { time: toTime(data.t[i]), open: data.o[i], high: data.h[i], low: data.l[i], close: data.c[i] };
      s = kind === "CANDLE"
        ? chart.addSeries(CandlestickSeries, { upColor: c.cup, downColor: c.cdown, wickUpColor: c.cup, wickDownColor: c.cdown, borderVisible: false })
        : chart.addSeries(BarSeries, { upColor: c.cup, downColor: c.cdown, thinBars: true });
      s.setData(ohlc);
    } else {
      const pts = new Array(n);
      for (let i = 0; i < n; i++) pts[i] = { time: toTime(data.t[i]), value: data.c[i] };
      s = kind === "AREA"
        ? chart.addSeries(AreaSeries, { lineColor: c.cline, topColor: c.sel, bottomColor: c.bg, lineWidth: 1 })
        : chart.addSeries(LineSeries, { color: c.cline, lineWidth: 1 });
      s.setData(pts);
    }
    main.current = s;
    patMarks.current = [];
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
    gauges.set("chart.extraSeries", extra.current.length);
    chart.priceScale("right").applyOptions({
      mode: compare ? PriceScaleMode.Percentage : log ? PriceScaleMode.Logarithmic : PriceScaleMode.Normal,
    });
    chart.timeScale().fitContent();
    writeReadout(n - 1);

    // Indicators: computed off the main thread, drawn when they arrive (unless superseded).
    if (indicators.length && n) {
      // Started on the first indicator request: line-only charts (FRED, BT) never pay for the worker.
      worker.current ??= new Worker(new URL("./indicators.worker.ts", import.meta.url), { type: "module" });
      const id = ++reqId.current;
      const w = worker.current;
      w.onmessage = (ev: MessageEvent<{ id: number; results: Record<string, Float64Array> }>) => {
        if (ev.data.id !== reqId.current || !chartRef.current) return;
        drawIndicators(chartRef.current, ev.data.results);
      };
      // Copies: the worker gets its own buffers so `data` stays usable here.
      w.postMessage({ id, which: indicators, series: { t: data.t.slice(), o: data.o.slice(), h: data.h.slice(), l: data.l.slice(), c: data.c.slice(), v: data.v.slice() } });
    } else {
      reqId.current++;
    }

    function drawIndicators(ch: IChartApi, r: Record<string, Float64Array>) {
      const line = (vals: Float64Array, color: string, pane = 0, title = "") => {
        const ls = ch.addSeries(LineSeries, { color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, title }, pane);
        const pts = [];
        for (let i = 0; i < vals.length; i++) pts.push(Number.isFinite(vals[i]) ? { time: toTime(data.t[i]), value: vals[i] } : { time: toTime(data.t[i]) });
        ls.setData(pts);
        extra.current.push(ls);
        return ls;
      };
      let pane = 1 + (comparePanes?.length ?? 0) + (lowerPane ? 1 : 0);
      if (r.SMA20) line(r.SMA20, c.acc, 0, "SMA20");
      if (r.SMA50) line(r.SMA50, c.warn, 0, "SMA50");
      if (r.EMA20) line(r.EMA20, c.fg, 0, "EMA20");
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
        pane++;
      }
      if (r.MACD) {
        const hist = ch.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false }, pane);
        const hp = [];
        for (let i = 0; i < r.MACD_HIST.length; i++) {
          const v = r.MACD_HIST[i];
          hp.push(Number.isFinite(v) ? { time: toTime(data.t[i]), value: v, color: v >= 0 ? c.up : c.down } : { time: toTime(data.t[i]) });
        }
        hist.setData(hp);
        extra.current.push(hist);
        line(r.MACD, c.acc, pane, "MACD");
        line(r.MACD_SIG, c.warn, pane);
        pane++;
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
          pts.push(Number.isFinite(r.SUPERTREND[i]) ? { time: toTime(data.t[i]), value: r.SUPERTREND[i], color: r.SUPERTREND_DIR[i] > 0 ? c.up : c.down } : { time: toTime(data.t[i]) });
        }
        ls.setData(pts);
        extra.current.push(ls);
      }
      if (r.PSAR) {
        const ls = ch.addSeries(LineSeries, { color: c.warn, lineVisible: false, pointMarkersVisible: true, pointMarkersRadius: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, title: "PSAR" }, 0);
        const pts = [];
        for (let i = 0; i < r.PSAR.length; i++) pts.push(Number.isFinite(r.PSAR[i]) ? { time: toTime(data.t[i]), value: r.PSAR[i] } : { time: toTime(data.t[i]) });
        ls.setData(pts);
        extra.current.push(ls);
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
      if (r.ATR) { osc(r.ATR, c.acc, "ATR14"); pane++; }
      if (r.STOCH_K) { osc(r.STOCH_K, c.acc, "STOCH K", [80, 20]); line(r.STOCH_D, c.warn, pane); pane++; }
      if (r.ADX) { osc(r.ADX, c.fg, "ADX14", [25]); line(r.ADX_PDI, c.up, pane); line(r.ADX_MDI, c.down, pane); pane++; }
      if (r.OBV) { osc(r.OBV, c.acc, "OBV"); pane++; }
      if (r.CCI) { osc(r.CCI, c.acc, "CCI20", [100, -100]); pane++; }
      if (r.WILLR) { osc(r.WILLR, c.acc, "%R14", [-20, -80]); pane++; }
      if (r.MFI) { osc(r.MFI, c.acc, "MFI14", [80, 20]); pane++; }

      // Pattern marks (rule-based, not signals) on the price series; SMC zones as dashed edges.
      const marks: SeriesMarker<Time>[] = [];
      if (r.PAT_CANDLE) {
        for (let i = 0; i < r.PAT_CANDLE.length; i++) {
          const info = PATTERN_INFO[r.PAT_CANDLE[i]];
          if (!info) continue;
          marks.push({ time: toTime(data.t[i]), position: info.dir < 0 ? "aboveBar" : "belowBar", shape: info.dir < 0 ? "arrowDown" : info.dir > 0 ? "arrowUp" : "circle", color: info.dir < 0 ? c.down : info.dir > 0 ? c.up : c.dim, text: info.short });
        }
      }
      if (r.SMC_SWING && r.SMC_BOS) {
        for (let i = 0; i < r.SMC_SWING.length; i++) {
          const sw = r.SMC_SWING[i];
          const b = r.SMC_BOS[i];
          if (sw) marks.push({ time: toTime(data.t[i]), position: sw > 0 ? "aboveBar" : "belowBar", shape: "circle", color: c.dim, size: 0.5 });
          if (b) marks.push({ time: toTime(data.t[i]), position: b > 0 ? "belowBar" : "aboveBar", shape: b > 0 ? "arrowUp" : "arrowDown", color: b > 0 ? c.up : c.down, text: Math.abs(b) === 2 ? "CHOCH" : "BOS" });
        }
        const z = r.SMC_ZONES ?? new Float64Array(0);
        for (let j = 0; j + 5 < z.length; j += 6) {
          const col = z[j] === 1 ? c.dim : z[j + 1] > 0 ? c.up : c.down;
          for (const price of [z[j + 4], z[j + 5]]) {
            const zs = ch.addSeries(LineSeries, { color: col, lineWidth: 1, lineStyle: LineStyle.Dashed, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, title: price === z[j + 4] ? (z[j] === 1 ? "FVG" : "OB") : "" }, 0);
            zs.setData([{ time: toTime(data.t[z[j + 2]]), value: price }, { time: toTime(data.t[z[j + 3]]), value: price }]);
            extra.current.push(zs);
          }
        }
      }
      patMarks.current = marks;
      applyMarkers();
      gauges.set("chart.extraSeries", extra.current.length);
      gauges.set("chart.markers", marks.length);
      const panes = ch.panes();
      for (let i = 1; i < panes.length; i++) panes[i].setHeight(panes[i] === undefined || i <= (comparePanes?.length ?? 0) + (lowerPane ? 1 : 0) ? 110 : 90);
    }
  }, [data, compare, type, log, indicators, lowerPane, comparePanes, ver]);

  /** Pattern marks and event marks share the price series' marker plugin. */
  function applyMarkers() {
    const api = markersApi.current;
    if (!api) return;
    const c = colors.current;
    const ev: SeriesMarker<Time>[] = (eventsRef.current ?? []).map((e) => ({ time: toTime(e.t), position: "aboveBar", shape: "square", color: c.fg, text: e.kind }));
    const all = [...patMarks.current, ...ev];
    all.sort((a, b) => (a.time as number) - (b.time as number));
    api.setMarkers(all);
    gauges.set("chart.markers", patMarks.current.length);
    gauges.set("chart.events", ev.length);
  }
  useEffect(() => {
    applyMarkers();
    writeReadout(cross.current.on ? cross.current.idx : data.c.length - 1);
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
    ctx.font = `11px ${c.font}`;
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
      const ts = chartRef.current?.timeScale();
      if (ts) ts.scrollToPosition(ts.scrollPosition() + bars, false);
    },
    zoom(factor) {
      const ts = chartRef.current?.timeScale();
      const r = ts?.getVisibleLogicalRange();
      if (!ts || !r) return;
      const width = Math.max(10, (r.to - r.from) * factor);
      ts.setVisibleLogicalRange({ from: r.to - width, to: r.to });
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
    live(price, timeMs, dayVolume) {
      const s = main.current;
      const b = last.current;
      if (!s || !b || compare) return;
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
      if (type === "CANDLE" || type === "OHLC") s.update({ time, open: b.o, high: b.h, low: b.l, close: b.c });
      else s.update({ time, value: b.c });
    },
  }));

  return (
    <div className="fn">
      <div ref={readout} className="line" />
      <div
        ref={box}
        className="chart"
        onClick={(e) => {
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
