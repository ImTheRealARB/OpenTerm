/**
 * Live tick store, written data-oriented (struct-of-arrays).
 *
 * Old shape: one JS object per symbol ({price, change, ...}), one array per tick row, a Map and a fresh Set per frame.
 * New shape: STRUCT-OF-ARRAYS. Instead of an array of objects, each field gets its own typed array and the
 * symbol's integer id (see symbols.ts) is the index:
 *
 *     live.price[id], live.change[id], live.pct[id], ...      (Float64Array, one slot per symbol id)
 *
 * Why this is faster: the numbers sit side by side in memory (the CPU cache loves that), there is nothing for the
 * garbage collector to track, and a field read is `array[id]` instead of "hash the string, find the object, read a property".
 *
 * "null" (a field the tick did not carry) is stored as NaN, because a typed array can only hold numbers.
 * Read it back with `Number.isNaN(x)` (or `x === x` is false for NaN).
 *
 * Steady state allocates NOTHING per tick or per frame: all buffers below are created once, grow by doubling only when a
 * new symbol (or a bigger burst) needs more room, and are reused every frame. The only per-frame allocation left is
 * the browser's own JSON.parse of the WebSocket text (see net/socket.ts) and the strings the painter needs for fillText.
 */
import { gauges, series } from "../perf/metrics";
import { bitClear, bitGrow, bitHas, bitSet } from "./bitset";
import { peekSymId, symId } from "./symbols";

/** Wire row: [symbol, price, change, pct, volume, high, low, time, src]. The JSON from the backend (see backend main.py). */
type Row = [string, number, number | null, number | null, number | null, number | null, number | null, number, string];

/** Compat view of one symbol (see `getLive`). Same fields the old `Live` object had. */
export interface Live {
  price: number;
  change: number | null;
  pct: number | null;
  volume: number | null;
  high: number | null;
  low: number | null;
  /** Epoch ms of the trade. */
  t: number;
  /** y = Yahoo stream, p = REST poll, s = SYNTHETIC, a = Alpaca IEX real-time trade (RT IEX) */
  src: string;
  /** Direction of the last price move: drives the persistent up/down colour. */
  dir: -1 | 0 | 1;
  /** Animation frame (flush number) of the last update: drives the one-frame highlight. */
  frame: number;
}

// ---------------------------------------------------------------------------------------------------------------
// Live columns (one slot per symbol id). The arrays are REPLACED when they grow, so always read them through `live.x`
// (never copy `live.price` into a long-lived variable).
// ---------------------------------------------------------------------------------------------------------------
export const live = {
  price: new Float64Array(0),
  change: new Float64Array(0),
  pct: new Float64Array(0),
  volume: new Float64Array(0),
  high: new Float64Array(0),
  low: new Float64Array(0),
  /** Epoch ms of the trade. */
  t: new Float64Array(0),
  /** Char code of the source letter (y p s a); 0 = none yet. */
  src: new Uint8Array(0),
  /** -1 down, 0 flat, 1 up. */
  dir: new Int8Array(0),
  /** Flush number of the last update (one-frame highlight). */
  frame: new Uint32Array(0),
};
/** Bitset: which ids have received at least one tick (`live.*[id]` is meaningful). */
let liveBits: Uint32Array = new Uint32Array(0);
export const hasLive = (id: number): boolean => bitHas(liveBits, id);

/**
 * The per-frame batch: the symbols that ticked since the last flush, deduplicated.
 * `ids[0..count)` lists them in arrival order; `bits` is the same set as a bitset so `has(id)` is O(1).
 * ONE object, reused every frame; a listener must not keep it (or its arrays) after it returns.
 */
export class TickBatch {
  ids: Uint32Array = new Uint32Array(0);
  count = 0;
  bits: Uint32Array = new Uint32Array(0);
  has(id: number): boolean {
    return bitHas(this.bits, id);
  }
}
const batch = new TickBatch();

/** Pending (not yet applied) values for the ids in `batch`. Same struct-of-arrays layout as `live`. */
const pend = {
  price: new Float64Array(0),
  change: new Float64Array(0),
  pct: new Float64Array(0),
  volume: new Float64Array(0),
  high: new Float64Array(0),
  low: new Float64Array(0),
  t: new Float64Array(0),
  src: new Uint8Array(0),
};

/** Copy `a` into a bigger array of the same type. */
function grown<T extends Float64Array | Uint8Array | Int8Array | Uint32Array>(a: T, n: number): T {
  const out = new (a.constructor as new (n: number) => T)(n);
  out.set(a);
  return out;
}

let cap = 0; // slots in every per-id array
/** Make every per-id array able to hold id `id`. Doubles, so it runs O(log n) times in total. */
function ensure(id: number): void {
  if (id < cap) return;
  const n = Math.max(256, cap * 2, id + 1);
  for (const k of ["price", "change", "pct", "volume", "high", "low", "t"] as const) {
    live[k] = grown(live[k], n);
    pend[k] = grown(pend[k], n);
  }
  live.src = grown(live.src, n);
  live.dir = grown(live.dir, n);
  live.frame = grown(live.frame, n);
  pend.src = grown(pend.src, n);
  liveBits = bitGrow(liveBits, n);
  batch.bits = bitGrow(batch.bits, n);
  batch.ids = grown(batch.ids, n); // a symbol appears at most once per batch, so n slots always suffice
  cap = n;
}

// ---------------------------------------------------------------------------------------------------------------
// Raw ticks: EVERY tick as it arrived (not deduplicated), for alerts. Also struct-of-arrays, reused every message.
// ---------------------------------------------------------------------------------------------------------------
export class RawTicks {
  /** Number of valid entries in the arrays below. */
  n = 0;
  /** Interned symbol id (see symbols.ts) of each tick. */
  id: Uint32Array = new Uint32Array(64);
  price: Float64Array = new Float64Array(64);
  /** NaN = the tick did not carry it. */
  change: Float64Array = new Float64Array(64);
  pct: Float64Array = new Float64Array(64);
  /** Char code of the source letter (y p s a). */
  src: Uint8Array = new Uint8Array(64);
  /** Make room for `n` ticks. Doubles, so it reallocates rarely (only when a bigger burst than ever before arrives). */
  reserve(n: number): void {
    if (n <= this.id.length) return;
    const m = Math.max(n, this.id.length * 2);
    this.id = grown(this.id, m);
    this.price = grown(this.price, m);
    this.change = grown(this.change, m);
    this.pct = grown(this.pct, m);
    this.src = grown(this.src, m);
  }
}
const raw = new RawTicks();

/** Called once per frame with the deduplicated batch. Read `batch.ids[0..count)` or ask `batch.has(id)`. */
export type TickListener = (batch: TickBatch, frame: number) => void;
/** Called once per WebSocket message with every tick in it (in order). Read the arrays; do not keep them. */
export type RawTickListener = (ticks: RawTicks) => void;

// Listener lists are plain arrays walked with an index loop (iterating a Set allocates an iterator each time).
// Adding or removing replaces the array (rare), so a walk in progress is never disturbed.
let listeners: TickListener[] = [];
let rawListeners: RawTickListener[] = [];

let oldestRecv = 0;
let scheduled = false;
let frame = 0;
let ticksSinceGauge = 0;
let gaugeAt = performance.now();

/**
 * Decode one "T" frame (already JSON-parsed) into the typed buffers. The wire carries strings, so this is the one place
 * that turns a symbol string into an id (one Map lookup per tick); after this line everything uses the id.
 */
export function ingest(rows: Row[], recvAt: number): void {
  const n = rows.length;
  raw.reserve(n);
  // Hoist the typed arrays into locals once: reading `pend.price` (a property) per tick costs more than the work itself.
  // `ensure` can REPLACE the per-id arrays when a new symbol needs more room, so the locals are reloaded right after it grows.
  let pPrice = pend.price, pChange = pend.change, pPct = pend.pct, pVol = pend.volume, pHigh = pend.high, pLow = pend.low;
  let pT = pend.t, pSrc = pend.src, bits = batch.bits, bIds = batch.ids;
  const rId = raw.id, rPrice = raw.price, rChange = raw.change, rPct = raw.pct, rSrc = raw.src;
  let count = batch.count;
  for (let i = 0; i < n; i++) {
    const r = rows[i];
    const id = symId(r[0]);
    if (id >= cap) {
      ensure(id);
      pPrice = pend.price; pChange = pend.change; pPct = pend.pct; pVol = pend.volume; pHigh = pend.high; pLow = pend.low;
      pT = pend.t; pSrc = pend.src; bits = batch.bits; bIds = batch.ids;
    }
    // `x == null ? NaN : x`: null (field not in this tick) becomes NaN, the typed-array spelling of "missing".
    const change = r[2] == null ? NaN : r[2];
    const pct = r[3] == null ? NaN : r[3];
    const volume = r[4] == null ? NaN : r[4];
    const high = r[5] == null ? NaN : r[5];
    const low = r[6] == null ? NaN : r[6];
    const src = r[8].charCodeAt(0);

    // Raw copy for alerts: only what they read (id, price, pct, change, src).
    rId[i] = id;
    rPrice[i] = r[1];
    rChange[i] = change;
    rPct[i] = pct;
    rSrc[i] = src;

    const w = id >>> 5;
    const m = 1 << (id & 31);
    if ((bits[w] & m) === 0) {
      // First tick of this symbol in this frame: take every field as is (NaN included).
      bits[w] |= m;
      bIds[count++] = id;
      pChange[id] = change;
      pPct[id] = pct;
      pVol[id] = volume;
      pHigh[id] = high;
      pLow[id] = low;
    } else {
      // Second tick in the same frame: the later one wins, but a field it did not carry (NaN) must not erase
      // a value the earlier tick had.
      if (change === change) pChange[id] = change;
      if (pct === pct) pPct[id] = pct;
      if (volume === volume) pVol[id] = volume;
      if (high === high) pHigh[id] = high;
      if (low === low) pLow[id] = low;
    }
    pPrice[id] = r[1];
    pT[id] = r[7];
    pSrc[id] = src;
  }
  batch.count = count;
  raw.n = n;
  const rl = rawListeners;
  for (let i = 0; i < rl.length; i++) rl[i](raw); // Phase 8: alerts (runs even when rAF is paused in a hidden tab)
  ticksSinceGauge += n;
  if (!oldestRecv) oldestRecv = recvAt;
  if (!scheduled) {
    scheduled = true;
    requestAnimationFrame(flush);
  }
}

// Tick-to-pixel timing without a closure per frame: a tiny ring of "oldest tick received" times plus two prebuilt callbacks.
// Same measurement as before: oldest buffered tick of the frame -> after that frame has been painted.
const T0_RING = 16;
const t0Ring = new Float64Array(T0_RING);
let t0Head = 0;
let t0Tail = 0;
const afterPaintDone = (): void => {
  series.tickToPixel.push(performance.now() - t0Ring[t0Tail++ & (T0_RING - 1)]);
};
const afterFrame = (): void => {
  setTimeout(afterPaintDone, 0); // rAF runs before paint; a task queued from it runs after
};

function flush(): void {
  scheduled = false;
  frame++;
  const ids = batch.ids;
  const count = batch.count;
  for (let k = 0; k < count; k++) {
    const id = ids[k];
    const p = pend.price[id];
    if (!bitHas(liveBits, id)) {
      bitSet(liveBits, id);
      live.price[id] = p;
      live.change[id] = pend.change[id];
      live.pct[id] = pend.pct[id];
      live.volume[id] = pend.volume[id];
      live.high[id] = pend.high[id];
      live.low[id] = pend.low[id];
      live.dir[id] = 0;
    } else {
      const old = live.price[id];
      live.dir[id] = p > old ? 1 : p < old ? -1 : live.dir[id];
      live.price[id] = p;
      // A NaN field means "this tick did not carry it": keep the value we already had.
      if (pend.change[id] === pend.change[id]) live.change[id] = pend.change[id];
      if (pend.pct[id] === pend.pct[id]) live.pct[id] = pend.pct[id];
      if (pend.volume[id] === pend.volume[id]) live.volume[id] = pend.volume[id];
      if (pend.high[id] === pend.high[id]) live.high[id] = pend.high[id];
      if (pend.low[id] === pend.low[id]) live.low[id] = pend.low[id];
    }
    live.t[id] = pend.t[id];
    live.src[id] = pend.src[id];
    live.frame[id] = frame;
  }
  const t0 = oldestRecv;
  oldestRecv = 0;
  try {
    const ls = listeners;
    for (let i = 0; i < ls.length; i++) ls[i](batch, frame);
  } finally {
    // Empty the batch: clear only the bits that were set (cheaper than wiping the whole bitset).
    for (let k = 0; k < count; k++) bitClear(batch.bits, ids[k]);
    batch.count = 0;
  }
  // Worst case of this frame: the oldest buffered tick, measured once the frame is on screen.
  t0Ring[t0Head++ & (T0_RING - 1)] = t0;
  requestAnimationFrame(afterFrame);

  const now = performance.now();
  if (now - gaugeAt >= 1000) {
    gauges.set("ws.ticksPerSec", (ticksSinceGauge * 1000) / (now - gaugeAt));
    ticksSinceGauge = 0;
    gaugeAt = now;
  }
}

// ---------------------------------------------------------------------------------------------------------------
// Reading
// ---------------------------------------------------------------------------------------------------------------

/** Display labels by source letter; use `srcLabel(code)` on hot paths (no object lookup by string). */
export const SRC_LABEL: Record<string, string> = { y: "STREAM", p: "POLL", s: "SYNTHETIC", a: "RT IEX", k: "RT KITE" };
/** Char code of "s" (SYNTHETIC). */
export const SRC_SYNTHETIC = 115;
/** Label for a source char code. */
export function srcLabel(code: number): string {
  switch (code) {
    case 121:
      return "STREAM"; // y
    case 112:
      return "POLL"; // p
    case 115:
      return "SYNTHETIC"; // s
    case 97:
      return "RT IEX"; // a
    case 107:
      return "RT KITE"; // k
    default:
      return String.fromCharCode(code);
  }
}

/** NaN-as-null to real null, for the compat view and for formatters that take number | null. */
export const orNull = (x: number): number | null => (x === x ? x : null);

/**
 * Compat view of one symbol with the old `Live` shape. One small object per symbol, created on first use and kept
 * (getters read the typed arrays, so it is always current and nothing is copied per tick).
 * ADAPTER: used by the non-grid readers (GP, GIP, LivePrice, FXC, PORT) that touch one symbol per frame.
 * Grid columns and useLiveRows use the id-based columns above instead.
 */
class LiveView implements Live {
  constructor(private readonly id: number) {}
  get price() {
    return live.price[this.id];
  }
  get change() {
    return orNull(live.change[this.id]);
  }
  get pct() {
    return orNull(live.pct[this.id]);
  }
  get volume() {
    return orNull(live.volume[this.id]);
  }
  get high() {
    return orNull(live.high[this.id]);
  }
  get low() {
    return orNull(live.low[this.id]);
  }
  get t() {
    return live.t[this.id];
  }
  get src() {
    return String.fromCharCode(live.src[this.id]);
  }
  get dir() {
    return live.dir[this.id] as -1 | 0 | 1;
  }
  get frame() {
    return live.frame[this.id];
  }
}
const views: (LiveView | undefined)[] = [];

export function getLive(symbol: string): Live | undefined {
  const id = peekSymId(symbol);
  if (id < 0 || !bitHas(liveBits, id)) return undefined;
  return (views[id] ??= new LiveView(id));
}
export const currentFrame = () => frame;

export function onTicks(l: TickListener): () => void {
  listeners = [...listeners, l];
  return () => {
    listeners = listeners.filter((x) => x !== l);
  };
}

/** Every tick as it arrives, before frame batching: alert checks must not wait for (or miss) a paint. */
export function onRawTicks(l: RawTickListener): () => void {
  rawListeners = [...rawListeners, l];
  return () => {
    rawListeners = rawListeners.filter((x) => x !== l);
  };
}
