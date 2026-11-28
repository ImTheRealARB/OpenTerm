/**
 * OpenTerm Script on a chart: turn a script's output into what the chart draws (pure, so vitest runs it).
 * `chart/scriptLayer.ts` owns the chart objects (series, markers, price lines, the overlay canvas); this file owns every
 * decision about WHAT is drawn and in WHICH colour, plus the model of one script's output that a live tick updates.
 *
 *   plot()       -> a series (line, step line, histogram / columns, circles, area), per-bar colours kept
 *   hline()      -> a price line
 *   plotshape()  -> markers on the price series (a shape with location "absolute" sits in the bar: markers have no price)
 *   bgcolor()    -> a stripe over the bar, fill() -> the area between two plots   (both painted on the overlay canvas)
 *   label / line / box -> overlay canvas, x = bar index, y = price;  table -> a small DOM box (rows come from `tableRows`)
 *
 * Colours: the script's own when it gives one (`color.red`, `color.new(...)`); otherwise the theme's accent colours in turn.
 * Up / down colours are never used as a default (they mean price direction).
 */
import type { DrawingsOut, PlotOut, ScriptResult, ScriptTick } from "../script/index";
import type { ThemeColors } from "./chartBase";

// ---------------------------------------------------------------- colours

/** `#rrggbbaa` (what `color.new` makes) -> `rgba(...)`: the chart library parses `#rrggbb` but not 8 digits. Anything else unchanged. */
export function cssColor(c: string | null | undefined): string | undefined {
  if (c === null || c === undefined || c === "") return undefined;
  const m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(c);
  if (!m) return c;
  const a = Math.round((parseInt(m[4], 16) / 255) * 1000) / 1000;
  return `rgba(${parseInt(m[1], 16)},${parseInt(m[2], 16)},${parseInt(m[3], 16)},${a})`;
}

/** Does the colour carry its own transparency? An opaque fill over the candles would hide them, so the painter dims those. */
export function hasAlpha(c: string): boolean {
  return /^#[0-9a-f]{8}$/i.test(c) || /^rgba\(/i.test(c) || /^hsla\(/i.test(c);
}

/** The colour with another opacity (area fills): handles `#rrggbb`, `rgb(...)` and `rgba(...)`; anything else comes back unchanged. */
export function withAlpha(c: string, alpha: number): string {
  let m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(c);
  if (m) return `rgba(${parseInt(m[1], 16)},${parseInt(m[2], 16)},${parseInt(m[3], 16)},${alpha})`;
  m = /^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/i.exec(c);
  return m ? `rgba(${m[1]},${m[2]},${m[3]},${alpha})` : c;
}

/** One line for the chart's error row: names the script, says what is wrong and where (line:col, and the bar for a run-time error). */
export function scriptErrorText(name: string, e: { msg: string; line?: number; col?: number; bar?: number }, more = 0): string {
  const where = e.line ? ` (LINE ${e.line}:${e.col ?? 0}${e.bar !== undefined ? `, BAR ${e.bar}` : ""})` : e.bar !== undefined ? ` (BAR ${e.bar})` : "";
  return `SCRIPT ${name}: ${e.msg}${where}${more > 0 ? ` +${more} MORE` : ""}`;
}

/** Default colours for plots without one: accent colours only (no up / down), cycled by output number. */
export function defaultPalette(t: ThemeColors): string[] {
  return [t.acc, t.warn, t.val, t.fg, t.dim];
}

// ---------------------------------------------------------------- the model

/** One output of a script, with room to grow by one bar per live `append`. */
export interface ModelPlot {
  index: number;
  kind: PlotOut["kind"];
  title: string;
  style: string;
  /** Resolved colour (script's own, else a palette colour) as CSS. */
  color: string;
  /** A colour per bar when the script changed it while running; null = every bar uses `color`. null entries = `color`. */
  cols: (string | null)[] | null;
  linewidth: number;
  /** plot: the value; shape: 1 or the price; bgcolor: 1; NaN = nothing on that bar. */
  vals: Float64Array;
  location?: string;
  text?: string;
  price?: number;
  a?: number;
  b?: number;
}

export interface ScriptModel {
  name: string;
  /** Bars held. */
  n: number;
  times: Float64Array;
  plots: ModelPlot[];
  drawings: DrawingsOut;
}

export interface SeriesPoint {
  time: number;
  value?: number;
  color?: string;
}

export type LineKind = "line" | "step" | "histogram" | "circles" | "area";

export interface LineSpec {
  plot: number;
  title: string;
  kind: LineKind;
  color: string;
  lineWidth: number;
  points: SeriesPoint[];
}

export interface MarkSpec {
  time: number;
  position: "aboveBar" | "belowBar" | "inBar";
  shape: "arrowUp" | "arrowDown" | "circle" | "square";
  color: string;
  text: string;
}

export interface HLineSpec {
  plot: number;
  price: number;
  color: string;
  title: string;
  dash: "solid" | "dashed" | "dotted";
}

/** Growable copy of a typed array (capacity doubles, so a day of `append`s never copies per bar). */
function grown(a: Float64Array, need: number): Float64Array {
  if (a.length >= need) return a;
  const b = new Float64Array(Math.max(need, a.length + (a.length >> 1) + 16)).fill(NaN);
  b.set(a);
  return b;
}

/** `times` = the open time of every bar the script ran over (epoch seconds). */
export function buildModel(name: string, result: ScriptResult, times: ArrayLike<number>, theme: ThemeColors): ScriptModel {
  const n = times.length;
  const pal = defaultPalette(theme);
  let drawn = 0; // palette position counts coloured outputs only (hlines and fills take dim)
  const plots: ModelPlot[] = result.plots.map((p, index) => {
    const own = cssColor(p.color);
    const fallback = p.kind === "plot" ? pal[drawn++ % pal.length] : p.kind === "shape" ? theme.acc : p.kind === "bgcolor" ? theme.dim : theme.dim;
    const vals = new Float64Array(n).fill(NaN);
    if (p.values) vals.set(p.values.length > n ? p.values.subarray(0, n) : p.values);
    return {
      index,
      kind: p.kind,
      title: p.title,
      style: p.style,
      color: own ?? fallback,
      cols: p.colors ? p.colors.map((c) => cssColor(c) ?? null) : null,
      linewidth: p.linewidth ?? 1,
      vals,
      location: p.location,
      text: p.text,
      price: p.price,
      a: p.a,
      b: p.b,
    };
  });
  const t = new Float64Array(n);
  for (let i = 0; i < n; i++) t[i] = times[i];
  return { name, n, times: t, plots, drawings: result.drawings };
}

/** The colour of a plot on bar `i`. */
export function colorAt(p: ModelPlot, i: number): string {
  return p.cols?.[i] ?? p.color;
}

const LINE_KIND: Record<string, LineKind> = { line: "line", stepline: "step", histogram: "histogram", columns: "histogram", circles: "circles", area: "area" };

/** One point for the series of plot `p` on bar `i`: a gap (time only) where the script gave na. */
export function pointAt(m: ScriptModel, p: ModelPlot, i: number): SeriesPoint {
  const v = p.vals[i];
  if (!Number.isFinite(v)) return { time: m.times[i] };
  // a colour on the point only when it differs from the series colour (cheaper, and the default stays the series' option)
  const c = p.cols?.[i];
  return c && c !== p.color ? { time: m.times[i], value: v, color: c } : { time: m.times[i], value: v };
}

/** The series to draw: one per `plot()` output. */
export function lineSpecs(m: ScriptModel): LineSpec[] {
  const out: LineSpec[] = [];
  for (const p of m.plots) {
    if (p.kind !== "plot") continue;
    const points: SeriesPoint[] = new Array(m.n);
    for (let i = 0; i < m.n; i++) points[i] = pointAt(m, p, i);
    out.push({ plot: p.index, title: p.title, kind: LINE_KIND[p.style] ?? "line", color: p.color, lineWidth: Math.max(1, Math.min(4, Math.round(p.linewidth))), points });
  }
  return out;
}

export function hlineSpecs(m: ScriptModel): HLineSpec[] {
  const out: HLineSpec[] = [];
  for (const p of m.plots) {
    if (p.kind !== "hline" || p.price === undefined || !Number.isFinite(p.price)) continue;
    out.push({ plot: p.index, price: p.price, color: p.color, title: p.title, dash: p.style === "solid" ? "solid" : p.style === "dotted" ? "dotted" : "dashed" });
  }
  return out;
}

const SHAPES: Record<string, MarkSpec["shape"]> = {
  triangleup: "arrowUp", arrowup: "arrowUp", labelup: "arrowUp",
  triangledown: "arrowDown", arrowdown: "arrowDown", labeldown: "arrowDown",
  circle: "circle", cross: "circle", diamond: "square",
};

/** The marks of every shape output on bar `i` (the live tick re-makes only the newest bar's). */
export function marksAtBar(m: ScriptModel, i: number): MarkSpec[] {
  const out: MarkSpec[] = [];
  for (const p of m.plots) {
    if (p.kind !== "shape" || !Number.isFinite(p.vals[i])) continue;
    const loc = p.location ?? "abovebar";
    out.push({
      time: m.times[i],
      position: loc === "belowbar" ? "belowBar" : loc === "absolute" ? "inBar" : "aboveBar",
      shape: SHAPES[p.style] ?? "arrowUp",
      color: colorAt(p, i),
      text: p.text ?? "",
    });
  }
  return out;
}

export function allMarks(m: ScriptModel): MarkSpec[] {
  const out: MarkSpec[] = [];
  if (!m.plots.some((p) => p.kind === "shape")) return out;
  for (let i = 0; i < m.n; i++) out.push(...marksAtBar(m, i));
  return out;
}

/** How many outputs the script drew: every plot / hline / shape / fill / bgcolor, plus labels, lines, boxes and tables. (gauge `chart.scripts`) */
export function countOutputs(m: ScriptModel): number {
  const d = m.drawings;
  return m.plots.length + d.labels.length + d.lines.length + d.boxes.length + d.tables.length;
}

// ---------------------------------------------------------------- live ticks

export interface TickDelta {
  /** The chart's series and marks must be rebuilt from `lineSpecs` / `allMarks` (the tick did not fit the model). */
  resync: boolean;
  /** One series update per plot output: the newest bar's point. */
  points: { plot: number; point: SeriesPoint }[];
  /** The newest bar's time and the marks it now has (replace the old marks at that time). */
  barTime: number;
  marks: MarkSpec[];
  /** The model grew by a bar. */
  grew: boolean;
}

/**
 * Put a live tick (the newest bar's values only) into the model. A new bar needs `barTime`; an update keeps the bar's own time.
 * A tick whose plot count does not match the model (the script changed under us) asks for a resync instead of guessing.
 */
export function applyTick(m: ScriptModel, tick: ScriptTick, barTime: number): TickDelta {
  const none: TickDelta = { resync: true, points: [], barTime, marks: [], grew: false };
  if (tick.plots.length !== m.plots.length || tick.bar < 0 || tick.bar > m.n || tick.n !== (tick.bar === m.n ? m.n + 1 : m.n)) return none;
  const grew = tick.bar === m.n;
  const i = tick.bar;
  if (grew) {
    m.times = grown(m.times, i + 1);
    m.times[i] = barTime;
    m.n = i + 1;
  }
  const time = m.times[i];
  const points: TickDelta["points"] = [];
  m.plots.forEach((p, k) => {
    if (grew) {
      p.vals = grown(p.vals, i + 1);
      if (p.cols) p.cols.length = i + 1;
    }
    const t = tick.plots[k];
    p.vals[i] = t.v;
    if (t.color !== undefined) {
      const c = cssColor(t.color) ?? null;
      if (c !== null && c !== p.color && !p.cols) p.cols = new Array(m.n).fill(null);
      if (p.cols) p.cols[i] = c;
    } else if (p.cols) p.cols[i] = null;
    if (p.kind === "plot") points.push({ plot: p.index, point: pointAt(m, p, i) });
  });
  m.drawings = tick.drawings;
  return { resync: false, points, barTime: time, marks: marksAtBar(m, i), grew };
}

// ---------------------------------------------------------------- the overlay canvas

export interface PaintEnv {
  /** Width of the plot area (left of the price scale) and the height of the whole chart. */
  w: number;
  h: number;
  /** Height of the price pane: drawings (labels, lines, boxes) are clipped to it. */
  priceH: number;
  theme: ThemeColors;
  /** First and last bar index on screen (inclusive); outside this nothing is painted. */
  visible: [number, number];
  /** x of a logical bar index (bar centre), or null when the chart cannot say. */
  xOf(logical: number): number | null;
  /** y of a price on the PRICE series (labels, lines, boxes). */
  yMain(price: number): number | null;
  /** y of a value on plot `plot`'s own series (fills); null when that plot has no series. */
  yOf(plot: number, value: number): number | null;
}

/** Something a canvas 2D context can do; narrower than CanvasRenderingContext2D so a test can fake it. */
export interface Ctx2D {
  save(): void;
  restore(): void;
  beginPath(): void;
  moveTo(x: number, y: number): void;
  lineTo(x: number, y: number): void;
  closePath(): void;
  rect(x: number, y: number, w: number, h: number): void;
  clip(): void;
  fill(): void;
  stroke(): void;
  fillRect(x: number, y: number, w: number, h: number): void;
  strokeRect(x: number, y: number, w: number, h: number): void;
  fillText(text: string, x: number, y: number): void;
  measureText(text: string): { width: number };
  setLineDash(d: number[]): void;
  fillStyle: string | CanvasGradient | CanvasPattern;
  strokeStyle: string | CanvasGradient | CanvasPattern;
  lineWidth: number;
  globalAlpha: number;
  font: string;
}

const FILL_ALPHA = 0.18;

/** Paints bgcolor stripes, fills, boxes, lines and labels. Returns how many items it painted (what a test counts). */
export function paintScript(ctx: Ctx2D, m: ScriptModel, env: PaintEnv): number {
  let painted = 0;
  const [from, to] = [Math.max(0, env.visible[0]), Math.min(m.n - 1, env.visible[1])];
  ctx.save();
  ctx.font = `${env.theme.fs}px ${env.theme.font}`;
  ctx.lineWidth = 1;

  // bgcolor stripes: the whole height, one bar wide
  for (const p of m.plots) {
    if (p.kind !== "bgcolor") continue;
    for (let i = from; i <= to; i++) {
      if (!Number.isFinite(p.vals[i])) continue;
      const x0 = env.xOf(i - 0.5);
      const x1 = env.xOf(i + 0.5);
      if (x0 === null || x1 === null) continue;
      const col = colorAt(p, i);
      ctx.globalAlpha = hasAlpha(col) ? 1 : FILL_ALPHA;
      ctx.fillStyle = col;
      ctx.fillRect(Math.min(x0, x1), 0, Math.abs(x1 - x0), env.h);
      painted++;
    }
  }

  // fill between two plots: one polygon per run of bars where both have a value
  for (const p of m.plots) {
    if (p.kind !== "fill" || p.a === undefined || p.b === undefined) continue;
    const A = m.plots[p.a];
    const B = m.plots[p.b];
    if (!A || !B) continue;
    ctx.globalAlpha = hasAlpha(p.color) ? 1 : FILL_ALPHA;
    ctx.fillStyle = p.color;
    let run: { x: number; ya: number; yb: number }[] = [];
    const flush = () => {
      if (run.length >= 2) {
        ctx.beginPath();
        run.forEach((q, j) => (j ? ctx.lineTo(q.x, q.ya) : ctx.moveTo(q.x, q.ya)));
        for (let j = run.length - 1; j >= 0; j--) ctx.lineTo(run[j].x, run[j].yb);
        ctx.closePath();
        ctx.fill();
        painted++;
      }
      run = [];
    };
    for (let i = Math.max(0, from - 1); i <= Math.min(m.n - 1, to + 1); i++) {
      const va = A.vals[i];
      const vb = B.vals[i];
      const x = env.xOf(i);
      const ya = Number.isFinite(va) ? env.yOf(A.index, va) : null;
      const yb = Number.isFinite(vb) ? env.yOf(B.index, vb) : null;
      if (x === null || ya === null || yb === null) flush();
      else run.push({ x, ya, yb });
    }
    flush();
  }
  ctx.globalAlpha = 1;

  // boxes, lines, labels: clipped to the price pane (x = bar index, y = price)
  ctx.save();
  ctx.beginPath();
  ctx.rect(0, 0, env.w, env.priceH);
  ctx.clip();
  const d = m.drawings;
  for (const b of d.boxes) {
    const x0 = env.xOf(b.left);
    const x1 = env.xOf(b.right);
    const y0 = env.yMain(b.top);
    const y1 = env.yMain(b.bottom);
    if (x0 === null || x1 === null || y0 === null || y1 === null) continue;
    const bg = cssColor(b.bgcolor);
    if (bg) {
      ctx.globalAlpha = hasAlpha(bg) ? 1 : FILL_ALPHA;
      ctx.fillStyle = bg;
      ctx.fillRect(Math.min(x0, x1), Math.min(y0, y1), Math.abs(x1 - x0), Math.abs(y1 - y0));
      ctx.globalAlpha = 1;
    }
    ctx.strokeStyle = cssColor(b.color) ?? env.theme.dim;
    ctx.strokeRect(Math.min(x0, x1), Math.min(y0, y1), Math.abs(x1 - x0), Math.abs(y1 - y0));
    painted++;
  }
  for (const l of d.lines) {
    const x0 = env.xOf(l.x1);
    const x1 = env.xOf(l.x2);
    const y0 = env.yMain(l.y1);
    const y1 = env.yMain(l.y2);
    if (x0 === null || x1 === null || y0 === null || y1 === null) continue;
    ctx.strokeStyle = cssColor(l.color) ?? env.theme.fg;
    ctx.lineWidth = Math.max(1, Math.min(6, l.width));
    ctx.beginPath();
    ctx.moveTo(x0, y0);
    ctx.lineTo(x1, y1);
    ctx.stroke();
    painted++;
  }
  ctx.lineWidth = 1;
  for (const lb of d.labels) {
    const x = env.xOf(lb.x);
    const y = env.yMain(lb.y);
    if (x === null || y === null || lb.text === "") continue;
    const w = ctx.measureText(lb.text).width;
    const fs = env.theme.fs;
    // "label_down" points down at the price, so the text sits above it; "label_up" the other way round; the rest beside it
    const above = lb.style !== "label_up";
    const bx = lb.style === "label_left" ? x - w - 8 : lb.style === "label_right" ? x + 4 : x - w / 2 - 3;
    const by = lb.style === "label_left" || lb.style === "label_right" ? y - fs / 2 - 2 : above ? y - fs - 8 : y + 4;
    const bg = cssColor(lb.color);
    if (bg) {
      ctx.globalAlpha = hasAlpha(bg) ? 1 : 0.85;
      ctx.fillStyle = bg;
      ctx.fillRect(bx, by, w + 6, fs + 4);
      ctx.globalAlpha = 1;
    }
    ctx.fillStyle = cssColor(lb.textcolor) ?? env.theme.fg;
    ctx.fillText(lb.text, bx + 3, by + fs);
    painted++;
  }
  ctx.restore();
  ctx.restore();
  return painted;
}

// ---------------------------------------------------------------- tables

export interface TableCell {
  text: string;
  color: string | null;
  bgcolor: string | null;
}

/** A script table as rows of cells (missing cells are empty), for the small DOM box in the chart corner. */
export function tableRows(t: DrawingsOut["tables"][number]): TableCell[][] {
  const rows: TableCell[][] = [];
  for (let r = 0; r < t.rows; r++) rows.push(Array.from({ length: t.columns }, () => ({ text: "", color: null, bgcolor: null })));
  for (const c of t.cells) {
    if (c.row >= 0 && c.row < t.rows && c.column >= 0 && c.column < t.columns) rows[c.row][c.column] = { text: c.text, color: cssColor(c.color) ?? null, bgcolor: cssColor(c.bgcolor) ?? null };
  }
  return rows;
}
