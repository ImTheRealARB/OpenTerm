/**
 * GP drawings. Phase 19 had trend line (a ray), horizontal line and fib retracement; Phase 21 adds the rest of the usual
 * charting toolbox (lines, channels, shapes, text, measures, fib family, pitchfork, Gann fan, position tools, wave labels).
 *
 * Every drawing is anchored in (time, price), never in pixels or bar numbers, so it survives a change of range or interval.
 * This file is PURE geometry: ChartView / gpLayer supply the coordinate conversion (`Geo`) and paint the primitives
 * (`Prim`) this file returns; tests supply identity functions. Nothing here touches the DOM.
 */

/** Every tool, in the order the GP tool picker lists them (W key). New tools go at the END so picker keys keep their meaning. */
export const DRAW_KINDS = [
  "TREND", "HLINE", "FIB",
  "RAY", "XLINE", "VLINE", "CROSS",
  "PCHAN", "REGCH", "RECT", "ELLIPSE", "TRI", "PATH",
  "TEXT", "NOTE", "ARROWUP", "ARROWDN",
  "PRANGE", "DRANGE", "MEASURE",
  "FIBEXT", "FIBTIME", "FIBFAN", "PITCHFORK", "GANNFAN",
  "LONG", "SHORT",
  "XABCD", "ELLIOTT5", "ELLIOTTABC",
] as const;
export type DrawKind = (typeof DRAW_KINDS)[number];

export interface DPoint {
  t: number;
  p: number;
}
export interface Drawing {
  id: string;
  kind: DrawKind;
  pts: DPoint[];
  /** TEXT / NOTE: the text shown. LONG / SHORT: "ACCOUNT RISK%" (e.g. "100000 1"). Any other tool: its name in the object tree. */
  label?: string;
  /** Object tree: hidden drawings are not drawn and cannot be picked. */
  hidden?: boolean;
  /** Object tree: a locked drawing cannot be deleted or re-anchored until it is unlocked. */
  locked?: boolean;
}

/**
 * One row per tool: its on-screen name, how many anchors it takes (min..max; only PATH varies) and whether placing it asks
 * for text afterwards (`ask`: TEXT = the words to show, RISK = account size and risk % for the position planner).
 */
interface ToolSpec {
  name: string;
  min: number;
  max: number;
  ask?: "TEXT" | "RISK";
}
export const TOOLS: Record<DrawKind, ToolSpec> = {
  TREND: { name: "TREND LINE", min: 2, max: 2 },
  HLINE: { name: "HORIZONTAL LINE", min: 1, max: 1 },
  FIB: { name: "FIB RETRACEMENT", min: 2, max: 2 },
  RAY: { name: "RAY", min: 2, max: 2 },
  XLINE: { name: "EXTENDED LINE", min: 2, max: 2 },
  VLINE: { name: "VERTICAL LINE", min: 1, max: 1 },
  CROSS: { name: "CROSS LINE", min: 1, max: 1 },
  PCHAN: { name: "PARALLEL CHANNEL", min: 3, max: 3 },
  REGCH: { name: "REGRESSION CHANNEL", min: 2, max: 2 },
  RECT: { name: "RECTANGLE", min: 2, max: 2 },
  ELLIPSE: { name: "ELLIPSE", min: 2, max: 2 },
  TRI: { name: "TRIANGLE", min: 3, max: 3 },
  PATH: { name: "PATH", min: 2, max: 10 },
  TEXT: { name: "TEXT", min: 1, max: 1, ask: "TEXT" },
  NOTE: { name: "NOTE", min: 1, max: 1, ask: "TEXT" },
  ARROWUP: { name: "ARROW UP", min: 1, max: 1 },
  ARROWDN: { name: "ARROW DOWN", min: 1, max: 1 },
  PRANGE: { name: "PRICE RANGE", min: 2, max: 2 },
  DRANGE: { name: "DATE RANGE", min: 2, max: 2 },
  MEASURE: { name: "PRICE AND DATE RANGE", min: 2, max: 2 },
  FIBEXT: { name: "FIB EXTENSION", min: 3, max: 3 },
  FIBTIME: { name: "FIB TIME ZONES", min: 2, max: 2 },
  FIBFAN: { name: "FIB FAN", min: 2, max: 2 },
  PITCHFORK: { name: "PITCHFORK", min: 3, max: 3 },
  GANNFAN: { name: "GANN FAN", min: 2, max: 2 },
  LONG: { name: "LONG POSITION", min: 3, max: 3, ask: "RISK" },
  SHORT: { name: "SHORT POSITION", min: 3, max: 3, ask: "RISK" },
  XABCD: { name: "XABCD PATTERN", min: 5, max: 5 },
  ELLIOTT5: { name: "ELLIOTT IMPULSE (1-5)", min: 6, max: 6 },
  ELLIOTTABC: { name: "ELLIOTT CORRECTION (A-C)", min: 4, max: 4 },
};

/** Anchors a tool takes (the most it takes, for PATH). Kept under the Phase 19 names so older code reads the same. */
export const NEEDED = Object.fromEntries(DRAW_KINDS.map((k) => [k, TOOLS[k].max])) as Record<DrawKind, number>;
export const KIND_NAME = Object.fromEntries(DRAW_KINDS.map((k) => [k, TOOLS[k].name])) as Record<DrawKind, string>;
/** What each anchor of a tool means, shown while placing it (missing = "ANCHOR n"). */
export const ANCHOR_HINT: Partial<Record<DrawKind, string[]>> = {
  PCHAN: ["LINE START", "LINE END", "CHANNEL WIDTH"],
  FIBEXT: ["MOVE START", "MOVE END", "RETRACEMENT END"],
  PITCHFORK: ["HANDLE", "LEFT TINE", "RIGHT TINE"],
  GANNFAN: ["ORIGIN", "1/1 POINT"],
  LONG: ["ENTRY", "STOP", "TARGET"],
  SHORT: ["ENTRY", "STOP", "TARGET"],
  XABCD: ["X", "A", "B", "C", "D"],
  ELLIOTT5: ["0", "1", "2", "3", "4", "5"],
  ELLIOTTABC: ["0", "A", "B", "C"],
};

export const FIB_RATIOS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1];
export const FIB_EXT_RATIOS = [0, 0.382, 0.618, 1, 1.272, 1.618, 2, 2.618];
export const FIB_TIME_STEPS = [0, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89];
export const FIB_FAN_RATIOS = [0.382, 0.5, 0.618];
/** Gann fan angles as price/time multipliers of the 1/1 line the user drew. */
export const GANN_RATIOS: [number, number][] = [[8, 1], [4, 1], [3, 1], [2, 1], [1, 1], [1, 2], [1, 3], [1, 4], [1, 8]];
export const MAX_DRAWINGS = 200;
export const LABEL_MAX = 200;

export interface Geo {
  /** Pixel x of a time, or null when the chart cannot place it. */
  toX(t: number): number | null;
  toY(p: number): number | null;
  /** Drawing width in px (rays and levels run to the right edge). */
  width: number;
  /** Plot height in px (vertical lines run to it). Defaults to a tall value: the painter clips to the plot anyway. */
  height?: number;
  /** Fractional bar index of a time, and the x of a fractional bar index: the bar-counting tools (time zones) need both. */
  logicalOf?(t: number): number;
  xOfLogical?(l: number): number | null;
}

/** The bars a few tools read (regression channel fits closes; measure tools count bars). */
export interface BarsCtx {
  t: ArrayLike<number>;
  c: ArrayLike<number>;
}

/** Phase 19 primitive: a straight segment, optionally with a level label and price. */
export interface Seg {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  label?: string;
  /** Price a horizontal line or fib level stands at (for its label). */
  price?: number;
}

/** Colour meaning of a filled or tinted primitive (profit / loss, rise / fall). */
export type Tone = "up" | "down";

/** What the painter draws. Coordinates are CSS pixels inside the chart box. */
export type Prim =
  | ({ k: "seg"; dash?: boolean } & Seg)
  | { k: "poly"; xs: number[]; ys: number[]; closed: boolean; fill?: Tone; dash?: boolean }
  | { k: "ellipse"; cx: number; cy: number; rx: number; ry: number }
  | { k: "text"; x: number; y: number; text: string; tone?: Tone; box?: boolean; align?: "left" | "center" };

interface XY {
  x: number;
  y: number;
}

/** 0% is the end of the move, 100% its start (retracement back toward the start). */
export function fibLevels(p0: number, p1: number): { ratio: number; price: number }[] {
  return FIB_RATIOS.map((ratio) => ({ ratio, price: p1 - ratio * (p1 - p0) }));
}

/** Fib extension levels: projected from the end of the pullback (C) by ratios of the first move (A to B). */
export function fibExtLevels(a: number, b: number, c: number): { ratio: number; price: number }[] {
  return FIB_EXT_RATIOS.map((ratio) => ({ ratio, price: c + ratio * (b - a) }));
}

/** Fractional bar index of a time: between bars it interpolates, past either end it extrapolates by that end's bar step. */
export function timeToLogical(t: number, times: ArrayLike<number>): number {
  const n = times.length;
  if (n === 0) return NaN;
  if (n === 1) return 0;
  if (t <= times[0]) return (t - times[0]) / (times[1] - times[0]);
  if (t >= times[n - 1]) return n - 1 + (t - times[n - 1]) / (times[n - 1] - times[n - 2]);
  let lo = 0;
  let hi = n - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (times[mid] <= t) lo = mid;
    else hi = mid;
  }
  return lo + (t - times[lo]) / (times[lo + 1] - times[lo]);
}

/**
 * The bar time that holds a calendar date (YYYY-MM-DD, UTC end of day): the last bar opened by then, if that bar's own period
 * still covers it. A date with no bar (weekend, outside the data) gives null: it is skipped, never moved to a neighbour.
 */
export function snapDay(iso: string, times: ArrayLike<number>, intervalS: number): number | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  const n = times.length;
  if (!m || n === 0) return null;
  const eod = Date.UTC(+m[1], +m[2] - 1, +m[3], 23, 59, 59) / 1000;
  if (eod < times[0]) return null;
  let lo = 0;
  let hi = n - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (times[mid] <= eod) lo = mid;
    else hi = mid - 1;
  }
  return eod < times[lo] + Math.max(intervalS, 86400) ? times[lo] : null;
}

/** Phase 19 tools as segments (kept as is: the tests and the gauges count them). Other tools: use `prims`. */
export function segments(d: Drawing, g: Geo): Seg[] {
  if (d.pts.length < NEEDED[d.kind]) return []; // not fully anchored yet
  const px = d.pts.map((p) => ({ x: g.toX(p.t), y: g.toY(p.p) }));
  if (d.kind === "HLINE") {
    const y = px[0]?.y;
    return y == null ? [] : [{ x1: 0, y1: y, x2: g.width, y2: y, price: d.pts[0].p }];
  }
  if (px.some((p) => p.x === null || p.y === null)) return [];
  const [a, b] = px as { x: number; y: number }[];
  const [l, r] = a.x <= b.x ? [a, b] : [b, a];
  const end = Math.max(g.width, r.x);
  if (d.kind === "TREND") {
    const slope = r.x === l.x ? 0 : (r.y - l.y) / (r.x - l.x);
    return [{ x1: l.x, y1: l.y, x2: end, y2: r.x === l.x ? r.y : r.y + slope * (end - r.x) }];
  }
  const out: Seg[] = [];
  for (const lv of fibLevels(d.pts[0].p, d.pts[1].p)) {
    const y = g.toY(lv.price);
    if (y !== null) out.push({ x1: l.x, y1: y, x2: end, y2: y, label: `${(lv.ratio * 100).toFixed(1)}%`, price: lv.price });
  }
  out.push({ x1: a.x, y1: a.y, x2: b.x, y2: b.y });
  return out;
}

// --- small helpers -----------------------------------------------------------------------------------------------------

/** Price text inside drawings (levels, measures): 2 decimals, 4 under 1 (crypto and FX quotes). */
export function fmtP(p: number): string {
  if (!Number.isFinite(p)) return "-";
  return Math.abs(p) >= 1 || p === 0 ? p.toFixed(2) : p.toFixed(4);
}
const fmtSigned = (v: number, digits = 2) => `${v >= 0 ? "+" : ""}${v.toFixed(digits)}`;
const fmtInt = (v: number) => Math.round(v).toLocaleString("en-US");

/** A date (intraday: date and UTC time) for vertical-line labels. */
export function fmtTime(t: number): string {
  const iso = new Date(t * 1000).toISOString();
  return t % 86400 === 0 ? iso.slice(0, 10) : `${iso.slice(0, 10)} ${iso.slice(11, 16)}`;
}

function at(g: Geo, p: DPoint): XY | null {
  const x = g.toX(p.t);
  const y = g.toY(p.p);
  return x === null || y === null ? null : { x, y };
}

/** Every anchor in pixels, or null if any cannot be placed (off the chart's time or price range). */
function allAt(g: Geo, pts: DPoint[]): XY[] | null {
  const out: XY[] = [];
  for (const p of pts) {
    const q = at(g, p);
    if (!q) return null;
    out.push(q);
  }
  return out;
}

/** The point where a line from a through b leaves the plot (a ray from a). Vertical rays run to the top or bottom. */
function rayEnd(a: XY, b: XY, g: Geo): XY {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  if (dx === 0 && dy === 0) return b;
  const h = g.height ?? 4000;
  let k: number;
  if (dx > 0) k = (g.width - a.x) / dx;
  else if (dx < 0) k = -a.x / dx;
  else k = (dy > 0 ? h - a.y : -a.y) / dy;
  k = Math.max(k, 1); // never stop short of the second anchor
  return { x: a.x + dx * k, y: a.y + dy * k };
}

const seg = (a: XY, b: XY, extra: Partial<Extract<Prim, { k: "seg" }>> = {}): Prim => ({ k: "seg", x1: a.x, y1: a.y, x2: b.x, y2: b.y, ...extra });
const text = (x: number, y: number, s: string, extra: Partial<Extract<Prim, { k: "text" }>> = {}): Prim => ({ k: "text", x, y, text: s, ...extra });

/** Least-squares line through `ys[from..to]` against the bar index, plus the standard deviation of what it leaves over. */
export function regression(ys: ArrayLike<number>, from: number, to: number): { a: number; b: number; sd: number; n: number } | null {
  let n = 0;
  let sx = 0;
  let sy = 0;
  let sxx = 0;
  let sxy = 0;
  for (let i = from; i <= to; i++) {
    const y = ys[i];
    if (!Number.isFinite(y)) continue;
    n++;
    sx += i;
    sy += y;
    sxx += i * i;
    sxy += i * y;
  }
  if (n < 2) return null;
  const den = n * sxx - sx * sx;
  if (den === 0) return null;
  const b = (n * sxy - sx * sy) / den; // slope per bar
  const a = (sy - b * sx) / n; // value at bar index 0
  let ss = 0;
  for (let i = from; i <= to; i++) {
    const y = ys[i];
    if (Number.isFinite(y)) ss += (y - (a + b * i)) ** 2;
  }
  return { a, b, sd: Math.sqrt(ss / n), n };
}

/** First and last bar index whose time lies between two anchor times (either order), or null if none does. */
function barSpan(times: ArrayLike<number>, t0: number, t1: number): [number, number] | null {
  const lo = Math.min(t0, t1);
  const hi = Math.max(t0, t1);
  let first = -1;
  let last = -1;
  for (let i = 0; i < times.length; i++) {
    if (times[i] < lo) continue;
    if (times[i] > hi) break;
    if (first < 0) first = i;
    last = i;
  }
  return first < 0 ? null : [first, last];
}

/** Bars between two times, counted on the chart's own bar grid (fractional ends rounded). */
export function barsBetween(times: ArrayLike<number>, t0: number, t1: number): number {
  return Math.round(Math.abs(timeToLogical(t1, times) - timeToLogical(t0, times)));
}

export interface PositionStats {
  /** False when the anchors are in the wrong order (a long's stop above its entry...). `problem` says why. */
  ok: boolean;
  problem?: string;
  risk: number; // price distance entry -> stop
  reward: number; // price distance entry -> target
  rr: number; // reward / risk
  account?: number;
  riskPct?: number;
  riskCash?: number;
  /** Whole units to buy or sell so that hitting the stop loses `riskCash`. */
  size?: number;
}

/**
 * Long / short position planner. `label` is "ACCOUNT RISK%" as the user typed it ("100000 1" or "100000 1%"); without it the
 * stats still give risk / reward. This plans only: it places nothing (NO LIVE ORDERS).
 */
export function positionStats(kind: "LONG" | "SHORT", entry: number, stop: number, target: number, label?: string): PositionStats {
  const long = kind === "LONG";
  const risk = Math.abs(entry - stop);
  const reward = Math.abs(target - entry);
  const base: PositionStats = { ok: true, risk, reward, rr: risk > 0 ? reward / risk : NaN };
  if (long ? !(stop < entry && entry < target) : !(target < entry && entry < stop)) {
    return { ...base, ok: false, problem: long ? "A LONG NEEDS STOP < ENTRY < TARGET" : "A SHORT NEEDS TARGET < ENTRY < STOP" };
  }
  const m = /^\s*([\d,.]+)\s+([\d.]+)\s*%?\s*$/.exec(label ?? "");
  if (!m) return base;
  const account = Number(m[1].replace(/,/g, ""));
  const riskPct = Number(m[2]);
  if (!(account > 0) || !(riskPct > 0) || riskPct > 100) return base;
  const riskCash = (account * riskPct) / 100;
  return { ...base, account, riskPct, riskCash, size: Math.floor(riskCash / risk) };
}

/** Where a wave / pattern label sits: above a swing high, below a swing low (judged against its neighbours). */
function labelAt(ps: XY[], i: number, s: string): Prim {
  const prev = ps[i - 1];
  const next = ps[i + 1];
  const nb = [prev, next].filter(Boolean) as XY[];
  const high = nb.length ? nb.every((q) => ps[i].y <= q.y) : true; // smaller y = higher price
  return text(ps[i].x, high ? ps[i].y - 6 : ps[i].y + 14, s, { align: "center" });
}

const ratioText = (num: number, den: number) => (den === 0 ? "-" : Math.abs(num / den).toFixed(3));

/**
 * The primitives that draw one drawing. `bars` is needed by the regression channel and the bar-counting measures; without it
 * they draw nothing (never a guess). An anchor off the chart yields nothing, like `segments`.
 */
export function prims(d: Drawing, g: Geo, bars?: BarsCtx): Prim[] {
  const spec = TOOLS[d.kind];
  if (!spec || d.pts.length < spec.min) return [];
  switch (d.kind) {
    case "TREND":
    case "HLINE":
    case "FIB": {
      const ss = segments(d, g);
      // A fib's last segment is the link between its anchors: dashed, like Phase 19.
      return ss.map((s, i) => ({ k: "seg", ...s, dash: d.kind === "FIB" && i === ss.length - 1 && !s.label }));
    }
    case "VLINE": {
      const x = g.toX(d.pts[0].t);
      if (x === null) return [];
      return [seg({ x, y: 0 }, { x, y: g.height ?? 4000 }), text(x + 3, 12, fmtTime(d.pts[0].t))];
    }
    case "CROSS": {
      const q = at(g, d.pts[0]);
      if (!q) return [];
      return [seg({ x: q.x, y: 0 }, { x: q.x, y: g.height ?? 4000 }), seg({ x: 0, y: q.y }, { x: g.width, y: q.y }, { price: d.pts[0].p }), text(q.x + 3, 12, fmtTime(d.pts[0].t))];
    }
    case "TEXT":
    case "NOTE":
    case "ARROWUP":
    case "ARROWDN": {
      const q = at(g, d.pts[0]);
      if (!q) return [];
      if (d.kind === "ARROWUP") return [{ k: "poly", xs: [q.x, q.x - 6, q.x + 6], ys: [q.y + 2, q.y + 12, q.y + 12], closed: true, fill: "up" }];
      if (d.kind === "ARROWDN") return [{ k: "poly", xs: [q.x, q.x - 6, q.x + 6], ys: [q.y - 2, q.y - 12, q.y - 12], closed: true, fill: "down" }];
      const s = d.label?.trim() || "TEXT";
      // A note is pinned to its bar: a short stem and the text in a box above it. A text label sits on its anchor.
      return d.kind === "NOTE" ? [seg(q, { x: q.x, y: q.y - 14 }), text(q.x, q.y - 18, s, { box: true })] : [text(q.x, q.y, s)];
    }
  }
  const ps = allAt(g, d.pts);
  if (!ps) return [];
  const [a, b, c] = ps;
  switch (d.kind) {
    case "RAY":
      return [seg(a, rayEnd(a, b, g))];
    case "XLINE":
      return [seg(rayEnd(b, a, g), rayEnd(a, b, g))];
    case "PCHAN": {
      // Line A-B, its parallel through C (same slope, shifted vertically), and the dashed middle line.
      const slope = b.x === a.x ? 0 : (b.y - a.y) / (b.x - a.x);
      const dy = c.y - (a.y + slope * (c.x - a.x));
      const sh = (p: XY, k: number) => ({ x: p.x, y: p.y + dy * k });
      return [seg(a, b), seg(sh(a, 1), sh(b, 1)), seg(sh(a, 0.5), sh(b, 0.5), { dash: true })];
    }
    case "REGCH": {
      if (!bars) return [];
      const span = barSpan(bars.t, d.pts[0].t, d.pts[1].t);
      if (!span) return [];
      const r = regression(bars.c, span[0], span[1]);
      if (!r) return [];
      const out: Prim[] = [];
      // Centre line and +-2 standard deviations of the residuals, from the first to the last bar between the anchors.
      for (const k of [0, 2, -2]) {
        const y1 = g.toY(r.a + r.b * span[0] + k * r.sd);
        const y2 = g.toY(r.a + r.b * span[1] + k * r.sd);
        const x1 = g.toX(bars.t[span[0]]);
        const x2 = g.toX(bars.t[span[1]]);
        if (x1 === null || x2 === null || y1 === null || y2 === null) return [];
        out.push(seg({ x: x1, y: y1 }, { x: x2, y: y2 }, { dash: k !== 0 }));
      }
      const end = out[0] as Extract<Prim, { k: "seg" }>;
      out.push(text(end.x2 + 3, end.y2, `REG ${r.n} BARS +-2 SD ${fmtP(2 * r.sd)}`));
      return out;
    }
    case "RECT":
      return [{ k: "poly", xs: [a.x, b.x, b.x, a.x], ys: [a.y, a.y, b.y, b.y], closed: true }];
    case "ELLIPSE":
      return [{ k: "ellipse", cx: (a.x + b.x) / 2, cy: (a.y + b.y) / 2, rx: Math.abs(b.x - a.x) / 2, ry: Math.abs(b.y - a.y) / 2 }];
    case "TRI":
      return [{ k: "poly", xs: [a.x, b.x, c.x], ys: [a.y, b.y, c.y], closed: true }];
    case "PATH":
      return [{ k: "poly", xs: ps.map((q) => q.x), ys: ps.map((q) => q.y), closed: false }];
    case "PRANGE":
    case "DRANGE":
    case "MEASURE": {
      const [p0, p1] = [d.pts[0], d.pts[1]];
      const dp = p1.p - p0.p;
      const pct = p0.p !== 0 ? (dp / p0.p) * 100 : NaN;
      const tone: Tone = dp >= 0 ? "up" : "down";
      const days = Math.abs(p1.t - p0.t) / 86400;
      const nBars = bars ? barsBetween(bars.t, p0.t, p1.t) : null;
      const priceTxt = `${fmtSigned(dp)} (${Number.isFinite(pct) ? fmtSigned(pct) : "-"}%)`;
      const timeTxt = `${nBars === null ? "-" : nBars} BARS, ${days < 1 ? `${(days * 24).toFixed(1)} H` : `${days.toFixed(days < 10 ? 1 : 0)} DAYS`}`;
      const midX = (a.x + b.x) / 2;
      const midY = (a.y + b.y) / 2;
      const top = Math.min(a.y, b.y);
      if (d.kind === "PRANGE") {
        return [seg({ x: a.x, y: a.y }, { x: b.x, y: a.y }), seg({ x: a.x, y: b.y }, { x: b.x, y: b.y }), seg({ x: midX, y: a.y }, { x: midX, y: b.y }), text(midX, top - 4, priceTxt, { tone, align: "center" })];
      }
      if (d.kind === "DRANGE") {
        return [seg({ x: a.x, y: a.y }, { x: a.x, y: b.y }), seg({ x: b.x, y: a.y }, { x: b.x, y: b.y }), seg({ x: a.x, y: midY }, { x: b.x, y: midY }), text(midX, top - 4, timeTxt, { align: "center" })];
      }
      return [{ k: "poly", xs: [a.x, b.x, b.x, a.x], ys: [a.y, a.y, b.y, b.y], closed: true, fill: tone }, text(midX, top - 4, `${priceTxt} · ${timeTxt}`, { tone, align: "center" })];
    }
    case "FIBEXT": {
      const out: Prim[] = [seg(a, b, { dash: true }), seg(b, c, { dash: true })];
      for (const lv of fibExtLevels(d.pts[0].p, d.pts[1].p, d.pts[2].p)) {
        const y = g.toY(lv.price);
        if (y !== null) out.push({ k: "seg", x1: c.x, y1: y, x2: Math.max(g.width, c.x), y2: y, label: `${(lv.ratio * 100).toFixed(1)}%`, price: lv.price });
      }
      return out;
    }
    case "FIBTIME": {
      if (!g.logicalOf || !g.xOfLogical) return [];
      const l0 = g.logicalOf(d.pts[0].t);
      const step = g.logicalOf(d.pts[1].t) - l0;
      if (!Number.isFinite(step) || step === 0) return [];
      const out: Prim[] = [];
      for (const f of FIB_TIME_STEPS) {
        const x = g.xOfLogical(l0 + f * step);
        if (x === null) continue;
        out.push(seg({ x, y: 0 }, { x, y: g.height ?? 4000 }, { dash: f > 1 }), text(x + 2, 12, String(f)));
      }
      return out;
    }
    case "FIBFAN": {
      // Lines from the start of the move through the retracement levels of its end bar, each extended to the right edge.
      const out: Prim[] = [seg(a, rayEnd(a, b, g))];
      for (const r of FIB_FAN_RATIOS) {
        const y = g.toY(d.pts[1].p - r * (d.pts[1].p - d.pts[0].p));
        if (y === null) continue;
        const e = rayEnd(a, { x: b.x, y }, g);
        out.push(seg(a, e, { dash: true }), text(e.x - 34, e.y - 2, `${(r * 100).toFixed(1)}%`));
      }
      return out;
    }
    case "PITCHFORK": {
      // Median line from the handle through the middle of the two tines; the two tines run parallel to it.
      const m = { x: (b.x + c.x) / 2, y: (b.y + c.y) / 2 };
      const dir = { x: m.x - a.x, y: m.y - a.y };
      const tine = (p: XY) => seg(p, rayEnd(p, { x: p.x + dir.x, y: p.y + dir.y }, g));
      return [seg(a, rayEnd(a, m, g)), tine(b), tine(c), seg(b, c, { dash: true })];
    }
    case "GANNFAN": {
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const out: Prim[] = [];
      for (const [pr, tm] of GANN_RATIOS) {
        const e = rayEnd(a, { x: a.x + dx * tm, y: a.y + dy * pr }, g);
        out.push(seg(a, e, { dash: !(pr === 1 && tm === 1) }), text(e.x - 26, e.y - 2, `${pr}/${tm}`));
      }
      return out;
    }
    case "LONG":
    case "SHORT": {
      const [e, s, tg] = d.pts;
      const st = positionStats(d.kind, e.p, s.p, tg.p, d.label);
      const right = Math.max(b.x, c.x, a.x + 60);
      const ys = b.y; // the stop anchor's price, in pixels
      const yt = c.y; // the target anchor's price
      const zone = (y1: number, y2: number, fill: Tone): Prim => ({ k: "poly", xs: [a.x, right, right, a.x], ys: [y1, y1, y2, y2], closed: true, fill });
      const lines = [
        `${d.kind} ${fmtP(e.p)} · STOP ${fmtP(s.p)} · TARGET ${fmtP(tg.p)}`,
        st.ok ? `REWARD/RISK ${Number.isFinite(st.rr) ? st.rr.toFixed(2) : "-"}` : st.problem!,
        st.size !== undefined ? `RISK ${st.riskPct}% OF ${fmtInt(st.account!)} = ${fmtInt(st.riskCash!)} · SIZE ${fmtInt(st.size)}` : "SIZE: TYPE ACCOUNT AND RISK % (E.G. 100000 1)",
      ];
      return [
        zone(a.y, yt, "up"),
        zone(a.y, ys, "down"),
        seg({ x: a.x, y: a.y }, { x: right, y: a.y }),
        ...lines.map((s2, i) => text(a.x + 3, Math.min(a.y, ys, yt) - 4 - (lines.length - 1 - i) * 13, s2, i === 1 && !st.ok ? { tone: "down" } : {})),
      ];
    }
    case "XABCD": {
      const [X, A, B, C, D] = d.pts.map((p) => p.p);
      const out: Prim[] = [{ k: "poly", xs: ps.map((q) => q.x), ys: ps.map((q) => q.y), closed: false }, seg(ps[0], ps[2], { dash: true }), seg(ps[2], ps[4], { dash: true })];
      ["X", "A", "B", "C", "D"].forEach((s, i) => out.push(labelAt(ps, i, s)));
      // The ratios harmonic traders read: AB of XA, BC of AB, CD of BC, AD of XA.
      out.push(text((ps[0].x + ps[2].x) / 2, (ps[0].y + ps[2].y) / 2, ratioText(B - A, A - X), { align: "center" }));
      out.push(text((ps[1].x + ps[3].x) / 2, (ps[1].y + ps[3].y) / 2, ratioText(C - B, B - A), { align: "center" }));
      out.push(text((ps[2].x + ps[4].x) / 2, (ps[2].y + ps[4].y) / 2, ratioText(D - C, C - B), { align: "center" }));
      out.push(text(ps[4].x, ps[4].y + 28, `AD/XA ${ratioText(D - A, A - X)}`, { align: "center" }));
      return out;
    }
    case "ELLIOTT5":
    case "ELLIOTTABC": {
      const names = d.kind === "ELLIOTT5" ? ["0", "1", "2", "3", "4", "5"] : ["0", "A", "B", "C"];
      const out: Prim[] = [{ k: "poly", xs: ps.map((q) => q.x), ys: ps.map((q) => q.y), closed: false }];
      names.forEach((s, i) => out.push(labelAt(ps, i, `(${s})`)));
      return out;
    }
  }
  return [];
}

/**
 * What to draw while a tool is being placed: the full tool once every anchor is in (the cursor counts as the next anchor),
 * before that the anchors so far joined by a line, so the user sees where the next one goes.
 */
export function pendingPrims(kind: DrawKind, pts: DPoint[], g: Geo, bars?: BarsCtx): Prim[] {
  if (pts.length >= TOOLS[kind].min && (pts.length >= TOOLS[kind].max || kind === "PATH")) return prims({ id: "pending", kind, pts }, g, bars);
  const ps = allAt(g, pts);
  if (!ps || !ps.length) return [];
  return ps.length === 1 ? [{ k: "poly", xs: [ps[0].x - 3, ps[0].x + 3, ps[0].x + 3, ps[0].x - 3], ys: [ps[0].y - 3, ps[0].y - 3, ps[0].y + 3, ps[0].y + 3], closed: true }] : [{ k: "poly", xs: ps.map((q) => q.x), ys: ps.map((q) => q.y), closed: false }];
}

export function distToSegment(px: number, py: number, s: Seg): number {
  const dx = s.x2 - s.x1;
  const dy = s.y2 - s.y1;
  const len2 = dx * dx + dy * dy;
  if (len2 === 0) return Math.hypot(px - s.x1, py - s.y1);
  const t = Math.max(0, Math.min(1, ((px - s.x1) * dx + (py - s.y1) * dy) / len2));
  return Math.hypot(px - (s.x1 + t * dx), py - (s.y1 + t * dy));
}

/** Pixel distance from a point to a primitive's outline (text: its approximate box). */
export function distToPrim(px: number, py: number, p: Prim): number {
  if (p.k === "seg") return distToSegment(px, py, p);
  if (p.k === "text") {
    const w = p.text.length * 7;
    const x0 = p.align === "center" ? p.x - w / 2 : p.x;
    const inside = px >= x0 && px <= x0 + w && py >= p.y - 11 && py <= p.y + 2;
    return inside ? 0 : distToSegment(px, py, { x1: x0, y1: p.y - 4, x2: x0 + w, y2: p.y - 4 });
  }
  let xs: number[];
  let ys: number[];
  let closed = true;
  if (p.k === "ellipse") {
    // A 32-sided polygon is close enough for picking.
    xs = [];
    ys = [];
    for (let i = 0; i < 32; i++) {
      xs.push(p.cx + p.rx * Math.cos((i / 32) * 2 * Math.PI));
      ys.push(p.cy + p.ry * Math.sin((i / 32) * 2 * Math.PI));
    }
  } else {
    xs = p.xs;
    ys = p.ys;
    closed = p.closed;
  }
  let best = Infinity;
  const n = xs.length;
  for (let i = 0; i + 1 < n + (closed ? 1 : 0); i++) {
    const j = (i + 1) % n;
    best = Math.min(best, distToSegment(px, py, { x1: xs[i], y1: ys[i], x2: xs[j], y2: ys[j] }));
  }
  return n === 1 ? Math.hypot(px - xs[0], py - ys[0]) : best;
}

/** Id of the visible drawing nearest to the point, within `tol` px; the later drawing wins a tie. */
export function hitTest(ds: Drawing[], px: number, py: number, g: Geo, tol = 6, bars?: BarsCtx): string | null {
  let best: string | null = null;
  let bestD = tol;
  for (const d of ds) {
    if (d.hidden) continue;
    for (const p of prims(d, g, bars)) {
      const dist = distToPrim(px, py, p);
      if (dist <= bestD) {
        bestD = dist;
        best = d.id;
      }
    }
  }
  return best;
}

const finite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const isKind = (k: unknown): k is DrawKind => typeof k === "string" && (DRAW_KINDS as readonly string[]).includes(k);

/** Keeps only well-formed drawings (a bad stored entry must never break the chart). */
export function parseDrawings(raw: unknown): Drawing[] {
  if (!Array.isArray(raw)) return [];
  const out: Drawing[] = [];
  for (const d of raw) {
    if (out.length >= MAX_DRAWINGS) break;
    if (!d || typeof d !== "object") continue;
    const { id, kind, pts, label, hidden, locked } = d as Record<string, unknown>;
    if (typeof id !== "string" || !id || id.length > 24 || !isKind(kind)) continue;
    if (!Array.isArray(pts) || pts.length < TOOLS[kind].min || pts.length > TOOLS[kind].max) continue;
    if (!pts.every((p) => p && finite((p as DPoint).t) && finite((p as DPoint).p))) continue;
    const dr: Drawing = { id, kind, pts: pts.map((p) => ({ t: (p as DPoint).t, p: (p as DPoint).p })) };
    if (typeof label === "string" && label) dr.label = label.slice(0, LABEL_MAX);
    if (hidden === true) dr.hidden = true;
    if (locked === true) dr.locked = true;
    out.push(dr);
  }
  return out;
}

export function newId(ds: Drawing[]): string {
  const used = new Set(ds.map((d) => d.id));
  let n = 1;
  while (used.has(`d${n}`)) n++;
  return `d${n}`;
}

export function cycleSelection(ds: Drawing[], current: string | null, dir: 1 | -1): string | null {
  const vis = ds.filter((d) => !d.hidden);
  if (!vis.length) return null;
  const i = vis.findIndex((d) => d.id === current);
  if (i < 0) return dir > 0 ? vis[0].id : vis[vis.length - 1].id;
  return vis[(i + dir + vis.length) % vis.length].id;
}
