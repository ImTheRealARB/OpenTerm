/**
 * Price chart core used by GP (and PERF CHART for load tests). Canvas rendering via TradingView
 * Lightweight Charts (Apache-2.0, attribution shown in GP's status line and README).
 * Indicators run in a Web Worker; live ticks update the last bar in place.
 */
import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import {
  AreaSeries, BarSeries, CandlestickSeries, ColorType, CrosshairMode, HistogramSeries, LineSeries,
  PriceScaleMode, TickMarkType, createChart,
  type IChartApi, type ISeriesApi, type SeriesType, type Time, type UTCTimestamp,
} from "lightweight-charts";
import { fmtBig, fmtPrice } from "../format";
import { displayVersion } from "../settings/runtime";
import { useStore } from "../state/store";
import type { IndicatorName } from "./indicators";

export type ChartType = "CANDLE" | "OHLC" | "LINE" | "AREA";
export const CHART_TYPES: ChartType[] = ["CANDLE", "OHLC", "LINE", "AREA"];

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

export interface ChartHandle {
  pan(bars: number): void;
  zoom(factor: number): void;
  crosshair(on: boolean): void;
  crosshairStep(delta: number): void;
  live(price: number, timeMs: number, dayVolume: number | null): void;
}

interface Props {
  data: BarData;
  compare?: { symbol: string; t: Float64Array; c: Float64Array } | null;
  type: ChartType;
  log: boolean;
  indicators: IndicatorName[];
  /** Single-value series (FRED): the readout shows `<date> <label> <value>` instead of O/H/L/C/V. */
  readoutLabel?: string;
}

const INTERVAL_S: Record<string, number> = {
  "1m": 60, "2m": 120, "5m": 300, "15m": 900, "30m": 1800, "60m": 3600, "90m": 5400,
  "1d": 86400, "1wk": 7 * 86400, "1mo": 31 * 86400,
};

function themeColors() {
  const cs = getComputedStyle(document.documentElement);
  const v = (n: string) => cs.getPropertyValue(n).trim();
  return { bg: v("--bg"), fg: v("--fg"), dim: v("--fg-dim"), up: v("--up"), down: v("--down"), line: v("--line"), acc: v("--accent"), warn: v("--warn"), sel: v("--sel"), font: v("--font") };
}

const toTime = (s: number) => s as UTCTimestamp;

function formatters(tz: string, intraday: boolean) {
  const opts = { timeZone: tz } as const;
  const time = new Intl.DateTimeFormat("en-GB", { ...opts, hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  const day = new Intl.DateTimeFormat("en-GB", { ...opts, day: "2-digit", month: "short" });
  const month = new Intl.DateTimeFormat("en-GB", { ...opts, month: "short" });
  const year = new Intl.DateTimeFormat("en-GB", { ...opts, year: "numeric" });
  const full = new Intl.DateTimeFormat("en-GB", { ...opts, day: "2-digit", month: "short", year: "numeric", ...(intraday ? { hour: "2-digit", minute: "2-digit", hourCycle: "h23" } : {}) });
  const ms = (t: Time) => (t as number) * 1000;
  return {
    tick: (t: Time, type: TickMarkType) =>
      type === TickMarkType.Year ? year.format(ms(t)) : type === TickMarkType.Month ? month.format(ms(t)) : type === TickMarkType.DayOfMonth ? day.format(ms(t)) : time.format(ms(t)),
    full: (t: Time) => full.format(ms(t)).toUpperCase(),
  };
}

function ChartViewInner({ data, compare, type, log, indicators, readoutLabel }: Props, ref: React.Ref<ChartHandle>) {
  const box = useRef<HTMLDivElement>(null);
  const readout = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const main = useRef<ISeriesApi<SeriesType> | null>(null);
  const vol = useRef<ISeriesApi<"Histogram"> | null>(null);
  const extra = useRef<ISeriesApi<SeriesType>[]>([]);
  const last = useRef<{ t: number; o: number; h: number; l: number; c: number; v: number } | null>(null);
  const cross = useRef({ on: false, idx: -1 });
  const fmt = useRef(formatters(data.tz, (INTERVAL_S[data.interval] ?? 86400) < 86400));
  const worker = useRef<Worker | null>(null);
  const reqId = useRef(0);

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
      `C ${fmtPrice(data.c[i])}  V ${fmtBig(data.v[i])}` + (Number.isFinite(chg) ? `  ${chg >= 0 ? "+" : ""}${chg.toFixed(2)}%` : "");
    el.className = "line " + (chg > 0 ? "up" : chg < 0 ? "down" : "");
  };

  // Chart instance: created once per panel.
  useEffect(() => {
    const c = colors.current;
    const chart = createChart(box.current!, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: c.bg }, textColor: c.dim, fontFamily: c.font, fontSize: 11, attributionLogo: false, panes: { separatorColor: c.line, enableResize: false } },
      grid: { vertLines: { color: c.sel }, horzLines: { color: c.sel } },
      rightPriceScale: { borderColor: c.line },
      timeScale: { borderColor: c.line, timeVisible: (INTERVAL_S[data.interval] ?? 86400) < 86400, secondsVisible: false, rightOffset: 3 },
      crosshair: { mode: CrosshairMode.Normal, vertLine: { color: c.dim, labelBackgroundColor: c.sel }, horzLine: { color: c.dim, labelBackgroundColor: c.sel } },
      kineticScroll: { mouse: false, touch: false },
      localization: { timeFormatter: (t: Time) => fmt.current.full(t) },
    });
    chart.subscribeCrosshairMove((p) => {
      if (p.logical == null) return;
      writeReadout(Math.round(p.logical as number));
    });
    chartRef.current = chart;
    worker.current = new Worker(new URL("./indicators.worker.ts", import.meta.url), { type: "module" });
    return () => {
      worker.current?.terminate();
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
      grid: { vertLines: { color: c.sel }, horzLines: { color: c.sel } },
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
    fmt.current = formatters(data.tz, (INTERVAL_S[data.interval] ?? 86400) < 86400);
    chart.applyOptions({
      timeScale: { timeVisible: (INTERVAL_S[data.interval] ?? 86400) < 86400, tickMarkFormatter: fmt.current.tick },
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
        ? chart.addSeries(CandlestickSeries, { upColor: c.up, downColor: c.down, wickUpColor: c.up, wickDownColor: c.down, borderVisible: false })
        : chart.addSeries(BarSeries, { upColor: c.up, downColor: c.down, thinBars: true });
      s.setData(ohlc);
    } else {
      const pts = new Array(n);
      for (let i = 0; i < n; i++) pts[i] = { time: toTime(data.t[i]), value: data.c[i] };
      s = kind === "AREA"
        ? chart.addSeries(AreaSeries, { lineColor: c.fg, topColor: c.sel, bottomColor: c.bg, lineWidth: 1 })
        : chart.addSeries(LineSeries, { color: c.fg, lineWidth: 1 });
      s.setData(pts);
    }
    main.current = s;
    last.current = n ? { t: data.t[n - 1], o: data.o[n - 1], h: data.h[n - 1], l: data.l[n - 1], c: data.c[n - 1], v: data.v[n - 1] } : null;

    if (!compare) {
      const v = chart.addSeries(HistogramSeries, { priceScaleId: "vol", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false });
      chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
      const bars = new Array(n);
      for (let i = 0; i < n; i++) bars[i] = { time: toTime(data.t[i]), value: Number.isFinite(data.v[i]) ? data.v[i] : 0, color: data.c[i] >= data.o[i] ? c.up : c.down };
      v.setData(bars);
      vol.current = v;
    } else {
      const cs = chart.addSeries(LineSeries, { color: c.acc, lineWidth: 1, title: compare.symbol });
      const pts = [];
      for (let i = 0; i < compare.t.length; i++) if (Number.isFinite(compare.c[i])) pts.push({ time: toTime(compare.t[i]), value: compare.c[i] });
      cs.setData(pts);
      extra.current.push(cs);
    }
    chart.priceScale("right").applyOptions({
      mode: compare ? PriceScaleMode.Percentage : log ? PriceScaleMode.Logarithmic : PriceScaleMode.Normal,
    });
    chart.timeScale().fitContent();
    writeReadout(n - 1);

    // Indicators: computed off the main thread, drawn when they arrive (unless superseded).
    if (indicators.length && n && worker.current) {
      const id = ++reqId.current;
      const w = worker.current;
      w.onmessage = (ev: MessageEvent<{ id: number; results: Record<string, Float64Array> }>) => {
        if (ev.data.id !== reqId.current || !chartRef.current) return;
        drawIndicators(chartRef.current, ev.data.results);
      };
      // Copies: the worker gets its own buffers so `data` stays usable here.
      w.postMessage({ id, which: indicators, series: { t: data.t.slice(), h: data.h.slice(), l: data.l.slice(), c: data.c.slice(), v: data.v.slice() } });
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
      let pane = 1;
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
      const panes = ch.panes();
      for (let i = 1; i < panes.length; i++) panes[i].setHeight(90);
    }
  }, [data, compare, type, log, indicators, ver]);

  useImperativeHandle(ref, () => ({
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
      <div ref={box} className="chart" />
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
