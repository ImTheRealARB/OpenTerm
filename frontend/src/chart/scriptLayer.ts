/**
 * OpenTerm Script on a GP chart: the controller (Phase 25 wave 2). Loaded with a dynamic `import()` by `gpLayer.ts` only when a
 * chart has `SCRIPT=`, so the entry bundle never carries it (the engine itself lives in the indicator worker's chunk).
 *
 * One `ScriptController` per chart. For every `SCRIPT=NAME(inputs)` it
 *   1. fetches the saved source (`scriptsApi.get`),
 *   2. sends it with the chart's bars to the worker (`script/worker.ts`); when the script needs `request(OTHER, ...)` bars it
 *      fetches them through the history client and sends the same message again,
 *   3. draws the answer: plots as series, hlines as price lines, shapes as markers (via the host), bgcolor / fill / labels / lines /
 *      boxes on the overlay canvas (`paint`), tables as a small DOM box,
 *   4. on live ticks sends the newest bar to the worker (one tick in flight per script, newer ticks merge) and updates only
 *      the newest bar of every output; alerts of that bar go through `fireScriptAlert`.
 * Nothing fails quietly: a compile error, a run-time error (line:col and bar), a missing script or a failed request becomes a
 * line on the chart (`ScriptReport`), labelled with the script's name.
 *
 * What to draw and in which colour is decided in `scriptDraw.ts` (pure, vitest). This file only touches chart objects.
 */
import { AreaSeries, HistogramSeries, LineSeries, LineStyle, LineType, type ISeriesApi, type IPriceLine, type SeriesType } from "lightweight-charts";
import { fireScriptAlert } from "../command/alerts";
import { gauges } from "../perf/metrics";
import { ApiError } from "../net/core";
import { marketApi } from "../net/marketApi";
import { scriptsApi } from "../net/scriptsApi";
import type { BarsAdj } from "../net/types";
import type { ScriptRef } from "../functions/gpArgs";
import type { BarCols } from "../script/index";
import type { ScriptInfo, ScriptReq, ScriptRes, ScriptTickReq, ScriptTickRes } from "../script/worker";
import { historyInterval, requestRange, scriptChartTf } from "../script/hostTf";
import { toTime } from "./chartBase";
import {
  allMarks, applyTick, buildModel, countOutputs, hlineSpecs, lineSpecs, paintScript, scriptErrorText, tableRows, withAlpha,
  type HLineSpec, type LineSpec, type MarkSpec, type ScriptModel, type TableCell,
} from "./scriptDraw";
import type { LiveBar, ScriptHost, ScriptReport } from "./scriptTypes";

let chartCounter = 0;

/** A source is re-read after this long: an edit made in the SCRIPT panel shows up on the next rebuild without a request per replay step. */
const SOURCE_TTL_MS = 10_000;

interface Entry {
  ref: ScriptRef;
  /** `name(inputs)`: a change of inputs replaces the entry. */
  sig: string;
  /** The worker's key for this run: `<chart>|<name>|run`. */
  key: string;
  phase: "loading" | "ready" | "error";
  /** Ready-to-show error line ("" = none). A run-time error still leaves the outputs up to that bar drawn, with the error beside them. */
  error: string;
  gen: number;
  source?: string;
  requests?: Record<string, BarCols>;
  info?: ScriptInfo;
  model?: ScriptModel;
  series: ISeriesApi<SeriesType>[];
  /** plot output number -> its series (fills read their coordinates from these). */
  plotSeries: Map<number, ISeriesApi<SeriesType>>;
  priceLines: { series: ISeriesApi<SeriesType>; line: IPriceLine }[];
  marks: MarkSpec[];
  /** `bar|message` of alerts already true when the script first ran: they are state, not news, and never fire. */
  seen: Set<string>;
  queue: { bar: LiveBar; isNew: boolean }[];
  inflight: boolean;
}

export class ScriptController {
  private entries = new Map<string, Entry>();
  private readonly id = `g${++chartCounter}`;
  private reqId = 0;
  private gen = 0;
  private disposed = false;
  private pendingRuns = new Map<number, { e: Entry; gen: number }>();
  private pendingTicks = new Map<number, { e: Entry; gen: number; time: number }>();
  private srcCache = new Map<string, { text: string; at: number }>();
  private reportSig = "";
  private tableSig = "";
  private tableRoot: HTMLDivElement | null = null;

  constructor(private host: ScriptHost) {}

  // ------------------------------------------------------------ what the chart layer calls

  /**
   * Make the chart show exactly `wanted`. An entry whose name and inputs are unchanged is left alone (no refetch, no redraw);
   * `blocked` is a reason the scripts cannot be drawn right now (they are removed and the reason is shown for each).
   */
  sync(wanted: ScriptRef[], blocked?: string): void {
    if (this.disposed) return;
    const want = blocked ? [] : wanted;
    const sigOf = (r: ScriptRef) => `${r.name}(${r.inputs.join("\u0001")})`;
    const keep = new Map(want.map((r) => [r.name, sigOf(r)]));
    for (const e of [...this.entries.values()]) if (keep.get(e.ref.name) !== e.sig) this.remove(e);
    for (const r of want) if (!this.entries.has(r.name)) this.add(r, sigOf(r));
    this.blocked = blocked ? Object.fromEntries(wanted.map((r) => [r.name, `SCRIPT ${r.name}: ${blocked}`])) : {};
    this.afterChange();
  }

  /** The chart was rebuilt and its series are gone: forget them (the next `sync` draws everything again). */
  reset(): void {
    for (const e of this.entries.values()) {
      e.series = [];
      e.plotSeries.clear();
      e.priceLines = [];
      e.gen = -1; // answers still on their way belong to the old chart
    }
    this.entries.clear();
    this.pendingRuns.clear();
    this.pendingTicks.clear();
    this.setTables();
    this.host.setMarks([]);
    this.setGauge();
  }

  seriesCount(): number {
    let n = 0;
    for (const e of this.entries.values()) n += e.series.length;
    return n;
  }

  /** The newest bar changed (`isNew`: a new bar opened). */
  onLive(bar: LiveBar, isNew: boolean): void {
    const b = { ...bar, v: Number.isFinite(bar.v) ? bar.v : 0 };
    for (const e of this.entries.values()) {
      if (e.phase !== "ready" || !e.model) continue;
      const q = e.queue;
      // A newer tick of the same bar replaces the one still waiting (it keeps "this opened a bar" if that one did).
      if (!isNew && q.length) q[q.length - 1] = { bar: b, isNew: q[q.length - 1].isNew };
      else q.push({ bar: b, isNew });
      this.pump(e);
    }
  }

  /** Overlay canvas: stripes, fills, boxes, lines, labels. Called from gpLayer's paint, which has done `setTransform` and `clearRect`. */
  paint(ctx: CanvasRenderingContext2D, g: { w: number; h: number; priceH: number; visible: [number, number]; xOf(l: number): number | null; yMain(p: number): number | null }): void {
    const box = this.host.box();
    if (!this.entries.size || !box) return;
    const theme = this.host.colors();
    const top0 = box.getBoundingClientRect().top;
    const tops = new Map<ISeriesApi<SeriesType>, number>();
    const paneTop = (s: ISeriesApi<SeriesType>) => {
      let t = tops.get(s);
      if (t === undefined) {
        t = (s.getPane().getHTMLElement()?.getBoundingClientRect().top ?? top0) - top0;
        tops.set(s, t);
      }
      return t;
    };
    for (const e of this.entries.values()) {
      if (e.phase !== "ready" || !e.model) continue;
      paintScript(ctx, e.model, {
        ...g,
        theme,
        yOf: (plot, value) => {
          const s = e.plotSeries.get(plot);
          const y = s ? s.priceToCoordinate(value) : null;
          return s && y !== null ? y + paneTop(s) : null;
        },
      });
    }
  }

  dispose(): void {
    this.disposed = true;
    this.host.post({ type: "script-drop", prefix: `${this.id}|` });
    this.tableRoot?.remove();
    this.tableRoot = null;
    this.entries.clear();
    this.pendingRuns.clear();
    this.pendingTicks.clear();
  }

  /** The worker's answers (`script` and `script-tick` messages). */
  onMessage(m: ScriptRes | ScriptTickRes): void {
    if (this.disposed) return;
    if (m.type === "script-tick") this.onTick(m);
    else this.onRun(m);
  }

  // ------------------------------------------------------------ entries

  private blocked: Record<string, string> = {};

  private add(ref: ScriptRef, sig: string): void {
    const e: Entry = {
      ref, sig, key: `${this.id}|${ref.name}|run`, phase: "loading", error: "", gen: ++this.gen,
      series: [], plotSeries: new Map(), priceLines: [], marks: [], seen: new Set(), queue: [], inflight: false,
    };
    this.entries.set(ref.name, e);
    void this.load(e, e.gen);
  }

  private remove(e: Entry): void {
    this.clearDrawn(e);
    e.gen = -1;
    this.entries.delete(e.ref.name);
    this.host.post({ type: "script-drop", prefix: `${this.id}|${e.ref.name}|` });
  }

  /** Is this still the entry on the chart, answering for the generation that asked? */
  private live(e: Entry, gen: number): boolean {
    return !this.disposed && e.gen === gen && this.entries.get(e.ref.name) === e;
  }

  private clearDrawn(e: Entry): void {
    const ch = this.host.chart();
    if (ch) {
      for (const pl of e.priceLines) {
        try {
          pl.series.removePriceLine(pl.line);
        } catch {
          /* the series was already replaced by a rebuild */
        }
      }
      for (const s of e.series) {
        try {
          ch.removeSeries(s);
        } catch {
          /* removed with the chart */
        }
      }
      this.host.layoutPanes(ch);
    }
    e.series = [];
    e.plotSeries.clear();
    e.priceLines = [];
    e.marks = [];
    e.model = undefined;
    e.queue.length = 0;
    e.inflight = false;
  }

  private fail(e: Entry, text: string): void {
    this.clearDrawn(e);
    e.phase = "error";
    e.error = text;
    this.afterChange();
  }

  // ------------------------------------------------------------ load -> run -> draw

  private async source(name: string): Promise<string> {
    const hit = this.srcCache.get(name);
    if (hit && Date.now() - hit.at < SOURCE_TTL_MS) return hit.text;
    const rec = await scriptsApi.get(name);
    this.srcCache.set(name, { text: rec.source, at: Date.now() });
    return rec.source;
  }

  private async load(e: Entry, gen: number): Promise<void> {
    let text: string;
    try {
      text = await this.source(e.ref.name);
    } catch (err) {
      if (!this.live(e, gen)) return;
      this.fail(e, err instanceof ApiError && err.status === 404 ? `SCRIPT NOT FOUND: ${e.ref.name}` : `SCRIPT ${e.ref.name}: ${err instanceof Error ? err.message : String(err)}`);
      return;
    }
    if (!this.live(e, gen)) return;
    e.source = text;
    this.run(e, gen);
  }

  /** Post the script and the chart's bars (copies: the chart keeps its own). */
  private run(e: Entry, gen: number): void {
    const d = this.host.data();
    const props = this.host.props();
    if (!d.c.length || !props || e.source === undefined) {
      this.fail(e, `SCRIPT ${e.ref.name}: NO BARS TO RUN ON`);
      return;
    }
    const id = ++this.reqId;
    this.pendingRuns.set(id, { e, gen });
    const msg: ScriptReq = {
      type: "script", id, key: e.key, name: e.ref.name, source: e.source, rawInputs: e.ref.inputs, symbol: props.symbol.toUpperCase(),
      chartTf: scriptChartTf(d.interval),
      bars: { t: d.t.slice(), o: d.o.slice(), h: d.h.slice(), l: d.l.slice(), c: d.c.slice(), v: d.v.slice() },
      requests: e.requests,
    };
    this.host.post(msg);
  }

  private onRun(m: ScriptRes): void {
    const p = this.pendingRuns.get(m.id);
    this.pendingRuns.delete(m.id);
    if (!p || !this.live(p.e, p.gen)) return;
    const e = p.e;
    if (m.status === "error") {
      const first = m.errors[0];
      this.fail(e, scriptErrorText(e.ref.name, { ...first, line: m.stage === "compile" ? first.line : 0 }, m.errors.length - 1));
      return;
    }
    e.info = m.info;
    if (m.status === "needs") {
      void this.fetchRequests(e, p.gen, m.needs);
      return;
    }
    this.draw(e, m);
  }

  /** The bars of other symbols / longer candles a script asked for with `request(...)`. */
  private async fetchRequests(e: Entry, gen: number, needs: { symbol: string; timeframe: string }[]): Promise<void> {
    const d = this.host.data();
    const range = this.host.props()?.range ?? "1Y";
    const got: Record<string, BarCols> = { ...(e.requests ?? {}) };
    try {
      for (const r of needs) {
        const itv = r.timeframe === "" ? d.interval : historyInterval(r.timeframe);
        if (!itv) throw new Error(`NO CANDLE LENGTH FOR TIMEFRAME ${r.timeframe.toUpperCase()}`);
        const env = await marketApi.history(r.symbol, r.timeframe === "" ? range : requestRange(r.timeframe, range), itv);
        got[`${r.symbol}|${r.timeframe}`] = colsOf(env.data);
        if (!this.live(e, gen)) return;
      }
    } catch (err) {
      if (!this.live(e, gen)) return;
      this.fail(e, `SCRIPT ${e.ref.name}: REQUEST DATA FAILED: ${err instanceof Error ? err.message : String(err)}`);
      return;
    }
    if (!this.live(e, gen)) return;
    e.requests = got;
    this.run(e, gen);
  }

  private draw(e: Entry, m: Extract<ScriptRes, { status: "ok" }>): void {
    const chart = this.host.chart();
    if (!chart) return;
    const d = this.host.data();
    const theme = this.host.colors();
    this.clearDrawn(e);
    const model = buildModel(e.ref.name, m.result, d.t, theme);
    e.model = model;
    const lines = lineSpecs(model);
    const hl = hlineSpecs(model);
    this.host.keepRange(() => {
      const pane = m.info.overlay || (!lines.length && !hl.length) ? 0 : chart.panes().length;
      for (const spec of lines) {
        const s = this.addSeries(spec, pane);
        e.series.push(s);
        e.plotSeries.set(spec.plot, s);
      }
      this.addHLines(e, hl, pane, d.t);
      this.host.layoutPanes(chart);
    });
    e.marks = allMarks(model);
    e.seen = new Set(m.result.alerts.filter((a) => a.bar === model.n - 1).map((a) => `${a.bar}|${a.message}`));
    e.phase = "ready";
    e.error = m.result.error ? scriptErrorText(e.ref.name, m.result.error) : "";
    this.afterChange();
    // a tick that arrived while the first run was on its way is not lost: the queue is only filled once the entry is ready, so nothing to replay
  }

  private addSeries(spec: LineSpec, pane: number): ISeriesApi<SeriesType> {
    const chart = this.host.chart()!;
    const common = { priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, title: spec.title };
    const time = (t: number) => toTime(t);
    let s: ISeriesApi<SeriesType>;
    if (spec.kind === "histogram") {
      s = chart.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false, title: spec.title, color: spec.color }, pane);
    } else if (spec.kind === "area") {
      s = chart.addSeries(AreaSeries, { ...common, lineColor: spec.color, topColor: withAlpha(spec.color, 0.3), bottomColor: withAlpha(spec.color, 0), lineWidth: spec.lineWidth as 1 | 2 | 3 | 4 }, pane);
    } else {
      s = chart.addSeries(
        LineSeries,
        {
          ...common,
          color: spec.color,
          lineWidth: spec.lineWidth as 1 | 2 | 3 | 4,
          lineType: spec.kind === "step" ? LineType.WithSteps : LineType.Simple,
          ...(spec.kind === "circles" ? { lineVisible: false, pointMarkersVisible: true, pointMarkersRadius: 3 } : {}),
        },
        pane,
      );
    }
    const pts = spec.points.map((p) =>
      p.value === undefined ? { time: time(p.time) } : p.color ? (spec.kind === "area" ? { time: time(p.time), value: p.value, lineColor: p.color } : { time: time(p.time), value: p.value, color: p.color }) : { time: time(p.time), value: p.value },
    );
    (s as ISeriesApi<"Line">).setData(pts as Parameters<ISeriesApi<"Line">["setData"]>[0]);
    return s;
  }

  /** hlines are price lines: on the price series (overlay), else on the script's first series, else on a hidden carrier that holds the price in view. */
  private addHLines(e: Entry, list: HLineSpec[], pane: number, t: Float64Array): void {
    if (!list.length) return;
    const chart = this.host.chart()!;
    let target: ISeriesApi<SeriesType> | null = pane === 0 ? this.host.main() : (e.series[0] ?? null);
    if (!target) {
      target = chart.addSeries(LineSeries, { lineVisible: false, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false }, pane);
      (target as ISeriesApi<"Line">).setData(list.slice(0, t.length).map((h, i) => ({ time: toTime(t[i]), value: h.price })));
      e.series.push(target);
    }
    for (const h of list) {
      const line = target.createPriceLine({
        price: h.price, color: h.color, lineWidth: 1, axisLabelVisible: true, title: h.title,
        lineStyle: h.dash === "solid" ? LineStyle.Solid : h.dash === "dotted" ? LineStyle.Dotted : LineStyle.Dashed,
      });
      e.priceLines.push({ series: target, line });
    }
  }

  // ------------------------------------------------------------ live ticks

  private pump(e: Entry): void {
    if (e.inflight || !e.queue.length || e.phase !== "ready") return;
    const op = e.queue.shift()!;
    const id = ++this.reqId;
    e.inflight = true;
    this.pendingTicks.set(id, { e, gen: e.gen, time: op.bar.t });
    const msg: ScriptTickReq = { type: "script-tick", id, key: e.key, isNew: op.isNew, bar: op.bar };
    this.host.post(msg);
  }

  private onTick(m: ScriptTickRes): void {
    const p = this.pendingTicks.get(m.id);
    this.pendingTicks.delete(m.id);
    if (!p) return;
    const e = p.e;
    e.inflight = false;
    if (!this.live(e, p.gen) || !e.model) return;
    if (!m.tick) {
      // The worker holds no run for this script (it was restarted). Say so; a refresh (F5) starts it again.
      this.fail(e, `SCRIPT ${e.ref.name}: LIVE UPDATES STOPPED (THE SCRIPT WORKER LOST ITS STATE): F5 TO RELOAD`);
      return;
    }
    const tick = m.tick;
    const delta = applyTick(e.model, tick, p.time);
    if (delta.resync) {
      this.fail(e, `SCRIPT ${e.ref.name}: OUT OF STEP WITH THE CHART: F5 TO RELOAD`);
      return;
    }
    for (const { plot, point } of delta.points) {
      const s = e.plotSeries.get(plot);
      if (!s) continue;
      const row = point.value === undefined ? { time: toTime(point.time) } : point.color ? { time: toTime(point.time), value: point.value, color: point.color } : { time: toTime(point.time), value: point.value };
      (s as ISeriesApi<"Line">).update(row as Parameters<ISeriesApi<"Line">["update"]>[0]);
    }
    // the newest bar's marks are re-made; older bars' stay. The marker plugin is touched only when that bar's marks changed.
    const hadMarks = e.marks.some((mk) => mk.time === delta.barTime);
    if (hadMarks || delta.marks.length) {
      e.marks = e.marks.filter((mk) => mk.time !== delta.barTime).concat(delta.marks);
      this.host.setMarks(this.allMarks());
    }
    const props = this.host.props();
    if (props) {
      for (const a of tick.alerts) {
        if (e.seen.has(`${a.bar}|${a.message}`)) continue;
        fireScriptAlert({ symbol: props.symbol, script: e.ref.name, message: a.message, barTime: delta.barTime, synthetic: props.synthetic });
      }
    }
    const err = tick.error ? scriptErrorText(e.ref.name, tick.error) : "";
    const errChanged = err !== e.error;
    e.error = err;
    this.setTables();
    this.setGauge();
    this.host.repaint();
    if (errChanged) this.report();
    this.pump(e);
  }

  // ------------------------------------------------------------ shared bookkeeping

  /** After any change: markers, tables, gauges, the status report to GP, a repaint. */
  private afterChange(): void {
    this.host.setMarks(this.allMarks());
    this.setTables();
    this.setGauge();
    this.host.publish();
    this.host.repaint();
    this.report();
  }

  private allMarks(): MarkSpec[] {
    const marks: MarkSpec[] = [];
    for (const e of this.entries.values()) marks.push(...e.marks);
    return marks;
  }

  private setGauge(): void {
    let n = 0;
    for (const e of this.entries.values()) if (e.phase === "ready" && e.model) n += countOutputs(e.model);
    gauges.set("chart.scripts", n);
  }

  private report(): void {
    const r: ScriptReport = {};
    for (const [name, text] of Object.entries(this.blocked)) r[name] = { state: "error", error: text };
    for (const e of this.entries.values()) r[e.ref.name] = { state: e.phase, error: e.error, title: e.info?.title, inputs: e.info?.inputs };
    const sig = JSON.stringify(r);
    if (sig === this.reportSig) return;
    this.reportSig = sig;
    this.host.props()?.onReport?.(r);
  }

  /** Tables of every ready script, as one small DOM box per corner. Rebuilt only when their text changed. */
  private setTables(): void {
    const box = this.host.box();
    const chart = this.host.chart();
    const all: { pos: string; rows: TableCell[][] }[] = [];
    for (const e of this.entries.values()) {
      if (e.phase === "ready" && e.model) for (const t of e.model.drawings.tables) all.push({ pos: t.position, rows: tableRows(t) });
    }
    const sig = JSON.stringify(all);
    if (sig === this.tableSig) return;
    this.tableSig = sig;
    this.tableRoot?.remove();
    this.tableRoot = null;
    if (!all.length || !box || !chart) return;
    const theme = this.host.colors();
    const root = document.createElement("div");
    root.setAttribute("data-testid", "gp-script-tables");
    root.style.cssText = "position:absolute;inset:0;pointer-events:none;z-index:4;";
    const right = (chart.priceScale("right").width() || 56) + 6;
    for (const pos of ["top_left", "top_right", "bottom_left", "bottom_right"]) {
      const mine = all.filter((t) => t.pos === pos);
      if (!mine.length) continue;
      const corner = document.createElement("div");
      const isRight = pos.endsWith("right");
      corner.style.cssText = `position:absolute;display:flex;flex-direction:column;gap:4px;align-items:${isRight ? "flex-end" : "flex-start"};${pos.startsWith("top") ? "top:4px" : "bottom:30px"};${isRight ? `right:${right}px` : "left:6px"};`;
      for (const t of mine) {
        const table = document.createElement("table");
        table.style.cssText = `border-collapse:collapse;background:${theme.bg};border:1px solid ${theme.line};font:${theme.fs}px ${theme.font};color:${theme.fg};`;
        for (const row of t.rows) {
          const tr = document.createElement("tr");
          for (const c of row) {
            const td = document.createElement("td");
            td.textContent = c.text;
            td.style.cssText = `padding:1px 5px;white-space:nowrap;${c.color ? `color:${c.color};` : ""}${c.bgcolor ? `background:${c.bgcolor};` : ""}`;
            tr.appendChild(td);
          }
          table.appendChild(tr);
        }
        corner.appendChild(table);
      }
      root.appendChild(corner);
    }
    box.appendChild(root);
    this.tableRoot = root;
  }
}

/** The history answer as the columns the script engine takes (bars without a close are dropped, like the chart does). */
function colsOf(b: BarsAdj): BarCols {
  const keep: number[] = [];
  for (let i = 0; i < b.t.length; i++) if (b.c[i] != null) keep.push(i);
  const col = (a: (number | null)[], fallback?: (number | null)[]) => Float64Array.from(keep, (i) => a[i] ?? fallback?.[i] ?? NaN);
  return { t: Float64Array.from(keep, (i) => b.t[i]), o: col(b.o, b.c), h: col(b.h, b.c), l: col(b.l, b.c), c: col(b.c), v: col(b.v) };
}

export function createScriptController(host: ScriptHost): ScriptController {
  return new ScriptController(host);
}

