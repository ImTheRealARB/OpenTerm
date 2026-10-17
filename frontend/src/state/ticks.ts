/**
 * Live tick store. Incoming ticks are buffered (latest per symbol) and applied once per animation
 * frame; listeners then repaint only what changed, imperatively, inside that same frame.
 * Live entries are mutated in place: no per-tick allocation, no React re-render.
 */
import { afterPaint, gauges, series } from "../perf/metrics";

export interface Live {
  price: number;
  change: number | null;
  pct: number | null;
  volume: number | null;
  high: number | null;
  low: number | null;
  /** Epoch ms of the trade. */
  t: number;
  /** y = Yahoo stream, p = REST poll, s = SYNTHETIC */
  src: string;
  /** Direction of the last price move: drives the persistent up/down colour. */
  dir: -1 | 0 | 1;
  /** Animation frame (flush number) of the last update: drives the one-frame highlight. */
  frame: number;
}

type Row = [string, number, number | null, number | null, number | null, number | null, number | null, number, string];
export type TickListener = (changed: ReadonlySet<string>, frame: number) => void;

const live = new Map<string, Live>();
const pending = new Map<string, Row>();
const listeners = new Set<TickListener>();
let oldestRecv = 0;
let scheduled = false;
let frame = 0;
let ticksSinceGauge = 0;
let gaugeAt = performance.now();

export function ingest(rows: Row[], recvAt: number): void {
  for (const r of rows) pending.set(r[0], r);
  for (const l of rawListeners) l(rows); // Phase 8: alerts (runs even when rAF is paused in a hidden tab)
  ticksSinceGauge += rows.length;
  if (!oldestRecv) oldestRecv = recvAt;
  if (!scheduled) {
    scheduled = true;
    requestAnimationFrame(flush);
  }
}

function flush(): void {
  scheduled = false;
  frame++;
  const changed = new Set<string>();
  for (const [sym, r] of pending) {
    let e = live.get(sym);
    if (!e) {
      e = { price: r[1], change: r[2], pct: r[3], volume: r[4], high: r[5], low: r[6], t: r[7], src: r[8], dir: 0, frame };
      live.set(sym, e);
    } else {
      e.dir = r[1] > e.price ? 1 : r[1] < e.price ? -1 : e.dir;
      e.price = r[1];
      if (r[2] != null) e.change = r[2];
      if (r[3] != null) e.pct = r[3];
      if (r[4] != null) e.volume = r[4];
      if (r[5] != null) e.high = r[5];
      if (r[6] != null) e.low = r[6];
      e.t = r[7];
      e.src = r[8];
      e.frame = frame;
    }
    changed.add(sym);
  }
  pending.clear();
  const t0 = oldestRecv;
  oldestRecv = 0;
  for (const l of listeners) l(changed, frame);
  // Worst case of this frame: the oldest buffered tick, measured once the frame is on screen.
  afterPaint(() => series.tickToPixel.push(performance.now() - t0));

  const now = performance.now();
  if (now - gaugeAt >= 1000) {
    gauges.set("ws.ticksPerSec", (ticksSinceGauge * 1000) / (now - gaugeAt));
    ticksSinceGauge = 0;
    gaugeAt = now;
  }
}

export const getLive = (symbol: string): Live | undefined => live.get(symbol);
export const currentFrame = () => frame;

export function onTicks(l: TickListener): () => void {
  listeners.add(l);
  return () => listeners.delete(l);
}

export const SRC_LABEL: Record<string, string> = { y: "STREAM", p: "POLL", s: "SYNTHETIC" };

// --- Phase 8: raw tick listeners ---
export type RawTickListener = (rows: readonly Row[]) => void;
const rawListeners = new Set<RawTickListener>();

/** Every tick as it arrives, before frame batching: alert checks must not wait for (or miss) a paint. */
export function onRawTicks(l: RawTickListener): () => void {
  rawListeners.add(l);
  return () => rawListeners.delete(l);
}
