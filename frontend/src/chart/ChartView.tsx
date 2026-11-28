/**
 * Price chart core used by every chart panel (GP, FRED, ECO, BT, MF, PRED, PERF CHART ...). Canvas rendering via
 * TradingView Lightweight Charts (Apache-2.0, attribution shown in GP's status line and README).
 * Live ticks update the last bar in place.
 *
 * This file is the PLAIN chart: candles / line / area types, volume, compare line, a lower pane, the readout,
 * pan / zoom / crosshair and live ticks. Everything only GP needs (indicators in a Web Worker, drawings,
 * markers, extra-symbol panes, alert lines, click-to-pick) lives in `gpLayer.ts` and switches on only when a
 * caller passes the `gp` prop. Callers without it (FRED, BT ...) get none of that code running.
 */
import "../components/dataColors.css";
import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import {
  AreaSeries, BarSeries, BaselineSeries, CandlestickSeries, ColorType, CrosshairMode, HistogramSeries, LineSeries, LineType,
  PriceScaleMode, TickMarkType, createChart,
  type IChartApi, type ISeriesApi, type SeriesType, type Time,
} from "lightweight-charts";
import { fmtBig, fmtPrice } from "../format";
import { gauges } from "../perf/metrics";
import { displayVersion } from "../settings/runtime";
import { useStore } from "../state/store";
import { toTime, themeColors, type BarData } from "./chartBase";
import { useGpLayer, type GpLayerProps, type GpOps } from "./gpLayer";

import { brickCount, brickDir, brickPrice, brickText, brickTime, buildBricks, type BrickResult } from "./bricks";
import { CHART_TYPES, isOhlcType, type ChartType } from "./chartTypes";
import { brickNote, isBrickType, volCandleNote } from "./brickNote";
import { onLink, publishLink } from "./linkBus";
import { PnfView, VolCandleView, type PnfData, type VolCandleData } from "./customSeries";
import { heikinAshi } from "./heikin";

export { CHART_TYPES };
export type { ChartType };

export type { BarData };
// The GP-only types moved to gpLayer.ts; re-exported so importers keep working.
export type { DrawState, ChartMarkerEvent, CustomItem, GpLayerProps } from "./gpLayer";

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
  /** Single-value series (FRED): the readout shows `<date> <label> <value>` instead of O/H/L/C/V. */
  readoutLabel?: string;
  /** BT: one extra line in a second pane on the same timestamps as `data` (drawdown). NaN = gap. */
  lowerPane?: { title: string; v: Float64Array } | null;
  /** GP only: indicators, drawings, markers, extra panes, alert lines, click-to-pick. Leave out for a plain chart. */
  gp?: GpLayerProps;
  /** Brick types (RENKO KAGI PNF RANGE): the box / reversal / range in price units. Absent = ATR(14) of the source bars. */
  brickBox?: number;
  /** PNF: boxes of reversal that start a new column (default 3). */
  brickRev?: number;
  /**
   * Called after every rebuild with the line to show on screen about how the chart was drawn (brick box used, volume-candle
   * caveats), or null for the other types. Passing a state setter is fine: it only re-renders when the text changes.
   */
  onNote?: (note: string | null) => void;
  /** Phase 22: this chart is in a link group; share the crosshair and / or the visible dates with the group's other charts. */
  sync?: { group: string; panelId: number; crosshair: boolean; range: boolean };
}

/** Types whose bars are not the source bars, or are rebuilt from history: a live tick cannot be applied in place, they refresh with the next history load. */
const skipsLiveTicks = (t: ChartType): boolean => t === "HEIKIN" || t === "VOLCANDLE" || isBrickType(t);

export const INTERVAL_S: Record<string, number> = {
  "1s": 1, "5s": 5, "15s": 15, "1m": 60, "2m": 120, "5m": 300, "15m": 900, "30m": 1800, "60m": 3600, "90m": 5400,
  "1d": 86400, "1wk": 7 * 86400, "1mo": 31 * 86400,
  // Phase 21 lengths the server builds from a smaller candle (backend resample.py). Nominal sizes: hour buckets restart each
  // trading day and a quarter / year is a calendar span, so these are the usual length, which is all the readout and live ticks need.
  "2h": 2 * 3600, "3h": 3 * 3600, "4h": 4 * 3600, "6h": 6 * 3600, "8h": 8 * 3600, "12h": 12 * 3600,
  "2d": 2 * 86400, "3d": 3 * 86400, "2wk": 14 * 86400, "3mo": 92 * 86400, "12mo": 366 * 86400,
};

/** The calendar date of an epoch second in an exchange's time zone (used only when a live tick starts a new bucket: rare). */
function localDay(t: number, tz: string): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: tz || "UTC" }).format(t * 1000);
}

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

type Colors = ReturnType<typeof themeColors>;

/**
 * Adds the series that draws a brick result and fills it with the marks.
 *  - Renko / three line break / range bars: the library's candles. Renko and line breaks have no wicks (the brick is the body).
 *  - Kagi: a line series drawn with steps (a sideways hop at each turn, then the vertical run). Each point carries the colour of the
 *    line that ends there: up colour = yang (thick on paper), down colour = yin. Thickness cannot change per point, so colour carries it.
 *  - Point and figure: the custom series in customSeries.ts, which draws a real X or O in every box.
 */
function addBrickSeries(chart: IChartApi, br: BrickResult, type: ChartType, c: Colors): ISeriesApi<SeriesType> {
  if (br.kind === "ohlc") {
    const s = chart.addSeries(CandlestickSeries, { upColor: c.cup, downColor: c.cdown, borderVisible: false, wickVisible: type === "RANGE", wickUpColor: c.cup, wickDownColor: c.cdown });
    const rows = new Array(br.t.length);
    for (let i = 0; i < rows.length; i++) rows[i] = { time: toTime(br.t[i]), open: br.o[i], high: br.h[i], low: br.l[i], close: br.c[i] };
    s.setData(rows);
    return s;
  }
  if (br.kind === "kagi") {
    const s = chart.addSeries(LineSeries, { color: c.cline, lineWidth: 2, lineType: LineType.WithSteps, priceLineVisible: false });
    const rows = new Array(br.t.length);
    for (let i = 0; i < rows.length; i++) rows[i] = { time: toTime(br.t[i]), value: br.v[i], color: br.yang[i] ? c.cup : c.cdown };
    s.setData(rows);
    return s;
  }
  const s = chart.addCustomSeries(new PnfView(), { upColor: c.cup, downColor: c.cdown, box: br.box.size, priceLineVisible: false, lastValueVisible: false });
  const rows: PnfData[] = new Array(br.t.length);
  for (let i = 0; i < rows.length; i++) rows[i] = { time: toTime(br.t[i]), lo: br.lo[i], hi: br.hi[i], up: br.up[i] };
  s.setData(rows);
  return s;
}

function ChartViewInner({ data, compare, type, log, readoutLabel, lowerPane, gp, brickBox, brickRev, onNote, sync }: Props, ref: React.Ref<ChartHandle>) {
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
  // Set while a brick chart is drawn: the chart then shows bricks, not the source bars, so the crosshair and readout must
  // index into the bricks (a bar index would point at the wrong mark). Null for every other type.
  const bricks = useRef<BrickResult | null>(null);
  const noteRef = useRef(onNote);
  noteRef.current = onNote;
  const cross = useRef({ on: false, idx: -1 });
  const hovering = useRef(false); // the mouse crosshair is over the chart
  const fmt = useRef(formatters(data.tz, (INTERVAL_S[data.interval] ?? 86400) < 86400, (INTERVAL_S[data.interval] ?? 86400) < 60));
  const dataRef = useRef(data);
  dataRef.current = data;
  const writeRef = useRef<(i: number) => void>(() => {});
  // Repainted by the GP layer's overlay (a no-op for plain charts); called from the rAF-coalesced schedule() below.
  const paintRef = useRef<() => void>(() => {});
  const rafRef = useRef(0);
  // The GP layer's hand-over points (see gpLayer.ts). Null when the caller passed no `gp` prop.
  const gpRef = useRef<GpOps | null>(null);
  const comparePanes = gp?.comparePanes;

  const colors = useRef(themeColors());
  // Phase 10: theme switch. Colours are re-read once per change (never per frame), then series are rebuilt.
  const ver = useStore(displayVersion, (v) => v);
  const seenVer = useRef(ver);

  /** How many marks the chart shows: bricks on a brick chart, else the source bars. */
  const shownCount = () => (bricks.current ? brickCount(bricks.current) : data.c.length);

  const writeReadout = (i: number) => {
    const el = readout.current;
    const br = bricks.current;
    if (el && br) {
      if (i < 0 || i >= brickCount(br)) return;
      const dir = brickDir(br, i);
      el.textContent = `${fmt.current.full(toTime(brickTime(br, i)))}  ${brickText(br, i, fmtPrice)}`;
      el.className = "line " + (dir > 0 ? "up" : "down");
      return;
    }
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
      (gpRef.current?.eventText(i) ?? "");
    el.className = "line " + (chg > 0 ? "up" : chg < 0 ? "down" : "");
  };
  writeRef.current = writeReadout;

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
      ro.disconnect();
      cancelAnimationFrame(rafRef.current);
      rafRef.current = 0;
      chart.remove();
      chartRef.current = null;
    };
  // Created once per panel. data.interval only seeds timeVisible here; the data effect re-applies it on interval change.
  // eslint-disable-next-line react-hooks/exhaustive-deps -- chart is created once; later interval changes are applied via applyOptions in the data effect
  }, []);

  // --- Phase 22: chart sync inside a link group (linkBus.ts) ---
  // Out: a mouse crosshair move (the library marks those with `sourceEvent`; moves WE make from another chart's message have
  // none, so they are never sent back) and visible-range changes. In: the same from the group's other charts. A range we
  // just applied echoes back as a change event, so changes in the next 150 ms after applying one are not sent on.
  const syncRef = useRef(sync);
  syncRef.current = sync;
  const quietUntil = useRef(0);
  useEffect(() => {
    const chart = chartRef.current;
    const host = box.current;
    if (!chart || !host || !sync) return;
    const onCross = (p: { time?: Time; sourceEvent?: unknown }) => {
      const s = syncRef.current;
      if (s?.crosshair && p.sourceEvent && p.time !== undefined) publishLink({ group: s.group, from: s.panelId, kind: "cross", t: p.time as number });
    };
    const onLeave = () => {
      const s = syncRef.current;
      if (s?.crosshair) publishLink({ group: s.group, from: s.panelId, kind: "cross", t: null });
    };
    const onRange = () => {
      const s = syncRef.current;
      const r = chart.timeScale().getVisibleRange();
      if (!s?.range || !r || performance.now() < quietUntil.current) return;
      publishLink({ group: s.group, from: s.panelId, kind: "range", a: r.from as number, b: r.to as number });
    };
    chart.subscribeCrosshairMove(onCross);
    chart.timeScale().subscribeVisibleTimeRangeChange(onRange);
    host.addEventListener("mouseleave", onLeave);
    const off = onLink((m) => {
      const s = syncRef.current;
      if (!s || m.group !== s.group || m.from === s.panelId || !main.current) return;
      const t = dataRef.current.t;
      if (m.kind === "cross" && s.crosshair && !cross.current.on) {
        if (m.t === null || !t.length) return chart.clearCrosshairPosition();
        // The last bar that opened at or before the other chart's time (another candle length or market can differ).
        let lo = 0;
        let hi = t.length - 1;
        while (lo < hi) {
          const mid = (lo + hi + 1) >> 1;
          if (t[mid] <= m.t) lo = mid;
          else hi = mid - 1;
        }
        chart.setCrosshairPosition(dataRef.current.c[lo], toTime(t[lo]), main.current);
      } else if (m.kind === "range" && s.range) {
        quietUntil.current = performance.now() + 150;
        chart.timeScale().setVisibleRange({ from: toTime(m.a), to: toTime(m.b) });
      }
    });
    return () => {
      off();
      chart.unsubscribeCrosshairMove(onCross);
      chart.timeScale().unsubscribeVisibleTimeRangeChange(onRange);
      host.removeEventListener("mouseleave", onLeave);
    };
  // Only joining or leaving a group (or another panel) re-subscribes; the on/off switches are read live through syncRef.
  // eslint-disable-next-line react-hooks/exhaustive-deps -- sync's switches are read through syncRef
  }, [sync?.group, sync?.panelId]);

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
    for (const s of [main.current, vol.current, ...extra.current]) if (s) chart.removeSeries(s);
    extra.current = [];
    gpRef.current?.reset(chart); // the GP layer removes its own series and forgets its state
    main.current = null;
    vol.current = null;

    const n = data.c.length;
    const kind: ChartType = compare ? "LINE" : type;
    let s: ISeriesApi<SeriesType>;
    let br: BrickResult | null = null; // the bricks drawn, when the type is a brick type
    let note: string | null = null; // the on-screen line about how this chart was drawn (handed to `onNote`)
    if (isBrickType(kind)) {
      // Brick types make their own marks from price moves (bricks.ts) and have their own, non-linear, time axis.
      br = buildBricks(kind, data, { box: brickBox, rev: brickRev });
      if (!br) throw new Error(`no brick transform for chart type ${kind}`);
      s = addBrickSeries(chart, br, kind, c);
      note = brickNote(kind, data.interval, br.box, { count: brickCount(br), capped: br.capped });
    } else if (kind === "VOLCANDLE") {
      // Candles whose body width follows volume: a custom series (customSeries.ts) because the library's candles have one width.
      const rows: VolCandleData[] = new Array(n);
      for (let i = 0; i < n; i++) rows[i] = { time: toTime(data.t[i]), open: data.o[i], high: data.h[i], low: data.l[i], close: data.c[i], vol: data.v[i] };
      const vs = chart.addCustomSeries(new VolCandleView(), { upColor: c.cup, downColor: c.cdown, priceLineVisible: false, lastValueVisible: false });
      vs.setData(rows);
      s = vs;
      note = volCandleNote(data.v);
    } else if (isOhlcType(kind)) {
      // Heikin Ashi draws smoothed bars (heikin.ts); every other OHLC type draws the real ones.
      const src = kind === "HEIKIN" ? heikinAshi(data.o, data.h, data.l, data.c) : data;
      const ohlc = new Array(n);
      for (let i = 0; i < n; i++) ohlc[i] = { time: toTime(data.t[i]), open: src.o[i], high: src.h[i], low: src.l[i], close: src.c[i] };
      s = kind === "OHLC"
        ? chart.addSeries(BarSeries, { upColor: c.cup, downColor: c.cdown, thinBars: true })
        : kind === "HIGHLOW"
          // High-low-close bars: the library cannot draw a bar without a tick, so the open tick is hidden and the REAL close tick stays.
          ? chart.addSeries(BarSeries, { upColor: c.cup, downColor: c.cdown, thinBars: true, openVisible: false })
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
      if (kind === "COLUMNS") {
        // Columns of closes, coloured like the volume bars (the bar closed up or down). The columns start just under the lowest
        // close (a visual floor, not zero): a price from 150 to 170 drawn from 0 would be a wall of identical columns.
        let lo = Infinity;
        let hi = -Infinity;
        for (let i = 0; i < n; i++) {
          pts[i].color = data.c[i] >= data.o[i] ? c.up : c.down;
          if (data.c[i] < lo) lo = data.c[i];
          if (data.c[i] > hi) hi = data.c[i];
        }
        const pad = (hi - lo) * 0.05 || Math.abs(lo) * 0.05 || 1;
        let floor = lo - pad;
        if (lo > 0 && floor <= 0) floor = lo * 0.9; // keep a log price scale legal
        s = chart.addSeries(HistogramSeries, { base: n ? floor : 0, color: c.up });
      } else {
        s = kind === "AREA"
          ? chart.addSeries(AreaSeries, { lineColor: c.cline, topColor: c.sel, bottomColor: c.bg, lineWidth: 1 })
          : kind === "BASELINE"
            ? chart.addSeries(BaselineSeries, { baseValue: { type: "price", price: base }, lineWidth: 1, topLineColor: c.cup, bottomLineColor: c.cdown, topFillColor1: c.cup + "55", topFillColor2: c.cup + "05", bottomFillColor1: c.cdown + "05", bottomFillColor2: c.cdown + "55" })
            : kind === "STEP"
              // Step line: each close is held flat until the next close (no slope between bars that the data does not have).
              ? chart.addSeries(LineSeries, { color: c.cline, lineWidth: 1, lineType: LineType.WithSteps })
              : chart.addSeries(LineSeries, { color: c.cline, lineWidth: 1 });
      }
      s.setData(pts);
    }
    main.current = s;
    bricks.current = br; // from here on the crosshair and readout index into the bricks (null = the source bars)
    gpRef.current?.afterMain(s); // marker plugin (GP only)
    last.current = n ? { t: data.t[n - 1], o: data.o[n - 1], h: data.h[n - 1], l: data.l[n - 1], c: data.c[n - 1], v: data.v[n - 1] } : null;

    // Series without volume (FRED, indices on some feeds) get no histogram: zero bars draw as a flat line.
    let hasVolume = false;
    for (let i = 0; i < n && !hasVolume; i++) hasVolume = data.v[i] > 0;
    // Brick charts get no volume bars either: those would sit at the source bars' times, not the bricks'.
    if (!compare && hasVolume && !br) {
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
    gpRef.current?.afterPanes(chart, 1 + (lowerPane ? 1 : 0)); // extra-symbol panes (GP only), below the lower pane
    chart.priceScale("right").applyOptions({
      mode: compare ? PriceScaleMode.Percentage : log ? PriceScaleMode.Logarithmic : PriceScaleMode.Normal,
    });
    chart.timeScale().fitContent();
    writeReadout(shownCount() - 1);

    gauges.set("chart.rebuilds", (gauges.get("chart.rebuilds") ?? 0) + 1);
    gauges.set("chart.bricks", br ? brickCount(br) : 0); // e2e reads this: the canvas is invisible to the DOM
    publish();
    noteRef.current?.(note);
  // Rebuilding the chart is expensive: it must happen only for these inputs, never because writeReadout is a new function each render.
  // eslint-disable-next-line react-hooks/exhaustive-deps -- rebuild only on data/compare/type/log/panes/theme/brick box; writeReadout is re-created every render
  }, [data, compare, type, log, lowerPane, comparePanes, ver, brickBox, brickRev]);

  /** Refreshes the gauges that e2e reads (the canvas is invisible to the DOM). */
  function publish() {
    gauges.set("chart.extraSeries", extra.current.length + (gpRef.current?.seriesCount() ?? 0));
    gauges.set("chart.panes", chartRef.current?.panes().length ?? 0);
  }

  // The GP layer. It MUST be called after the series effect above: its effects re-add indicators after a rebuild cleared them.
  const { overlay } = useGpLayer(
    { box, chartRef, main, colors, dataRef, cross, rafRef, paintRef, writeRef, publish },
    gpRef,
    gp,
    { data, compare, type, log, lowerPane, ver },
  );

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
        writeReadout(shownCount() - 1);
        return;
      }
      cross.current.idx = shownCount() - 1;
      this.crosshairStep(0);
    },
    crosshairStep(delta) {
      const chart = chartRef.current;
      if (!chart || !main.current || !cross.current.on) return;
      const br = bricks.current;
      const i = Math.max(0, Math.min(shownCount() - 1, cross.current.idx + delta));
      cross.current.idx = i;
      // On a brick chart the keyboard crosshair walks the bricks, at the brick's own time and price.
      chart.setCrosshairPosition(br ? brickPrice(br, i) : data.c[i], toTime(br ? brickTime(br, i) : data.t[i]), main.current);
      writeReadout(i);
      // Phase 22: a keyboard crosshair move is shared with the link group like a mouse one.
      const s = syncRef.current;
      if (s?.crosshair && !br) publishLink({ group: s.group, from: s.panelId, kind: "cross", t: data.t[i] });
    },
    lastPrice() {
      return last.current && Number.isFinite(last.current.c) ? last.current.c : null;
    },
    alertPrice() {
      const br = bricks.current;
      const px = cross.current.on ? (br ? brickPrice(br, cross.current.idx) : data.c[cross.current.idx]) : last.current?.c;
      return px !== undefined && Number.isFinite(px) ? px : null;
    },
    live(price, timeMs, dayVolume) {
      const s = main.current;
      const b = last.current;
      if (!s || !b || compare || skipsLiveTicks(type)) return; // Heikin Ashi, brick and volume-candle charts refresh with the next history load
      const iv = INTERVAL_S[data.interval] ?? 86400;
      const ts = Math.floor(timeMs / 1000);
      if (ts < b.t) return;
      let opened = false; // a new bar began with this tick (scripts then `append` instead of re-running the newest bar)
      if (ts < b.t + iv) {
        // Same bar: extend it.
        b.c = price;
        b.h = Math.max(b.h, price);
        b.l = Math.min(b.l, price);
        if (iv >= 86400 && dayVolume != null) b.v = dayVolume;
      } else if (iv < 86400) {
        // New intraday bucket, aligned to the interval grid.
        const t = b.t + Math.floor((ts - b.t) / iv) * iv;
        // Resampled hour candles (2h..12h) restart at each session's open (backend/openterm/resample.py), so the grid only holds
        // inside one local day; a 24-hour UTC market whose day divides evenly is the exception. Otherwise the new session's
        // first candle arrives with the next history load instead of being guessed on the wrong grid.
        if (iv > 3600 && !(data.tz === "UTC" && 86400 % iv === 0) && localDay(t, data.tz) !== localDay(b.t, data.tz)) return;
        Object.assign(b, { t, o: price, h: price, l: price, c: price, v: 0 });
        opened = true;
      } else {
        return; // new daily+ bar: arrives with the next history refresh rather than guessed here
      }
      const time = toTime(b.t);
      if (isOhlcType(type)) s.update({ time, open: b.o, high: b.h, low: b.l, close: b.c });
      else if (type === "COLUMNS") s.update({ time, value: b.c, color: b.c >= b.o ? colors.current.up : colors.current.down });
      else s.update({ time, value: b.c });
      // The volume bar under the candle follows too (same up / down colour rule as at build time).
      // A new intraday bucket gets its own bar; its volume is 0 until the next history load.
      const cols = colors.current;
      vol.current?.update({ time, value: Number.isFinite(b.v) ? b.v : 0, color: b.c >= b.o ? cols.up : cols.down });
      // Keep the readout current, unless a crosshair (keyboard or mouse) is parked on a bar: that bar's values must not jump.
      if (!cross.current.on && !hovering.current) writeRef.current(dataRef.current.c.length - 1);
      gpRef.current?.onLive({ ...b }, opened); // OpenTerm Script (GP only): the newest bar as it is now
    },
  }));

  return (
    <div className="fn">
      <div ref={readout} className="line" />
      <div
        ref={box}
        className="chart"
        onClick={gpRef.current?.onClick}
      >
        {gp && <canvas ref={overlay} style={{ position: "absolute", left: 0, top: 0, width: "100%", height: "100%", pointerEvents: "none", zIndex: 3 }} />}
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
