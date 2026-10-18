/**
 * Always-on instrumentation. Cheap by construction: fixed-size ring buffers, no allocation per sample.
 * Exposed on window.__openterm_perf for scripts/bench.
 */

export class Ring {
  private buf: Float64Array;
  private n = 0;
  private i = 0;
  constructor(size: number) {
    this.buf = new Float64Array(size);
  }
  push(v: number): void {
    this.buf[this.i] = v;
    this.i = (this.i + 1) % this.buf.length;
    if (this.n < this.buf.length) this.n++;
  }
  get size(): number {
    return this.n;
  }
  last(): number {
    return this.n ? this.buf[(this.i - 1 + this.buf.length) % this.buf.length] : NaN;
  }
  percentile(p: number): number {
    if (!this.n) return NaN;
    const a = Array.from(this.buf.subarray(0, this.n)).sort((x, y) => x - y);
    return a[Math.min(a.length - 1, Math.round((p / 100) * (a.length - 1)))];
  }
  clear(): void {
    this.n = 0;
    this.i = 0;
  }
}

/** Named latency series. */
export const series = {
  keyEcho: new Ring(256),
  cmdToPaint: new Ring(256),
  tickToPixel: new Ring(1024),
  frame: new Ring(600),
  wsRtt: new Ring(64),
  layoutLoad: new Ring(64),
  /** Phase 11: submitJob call to the painted frame showing that job's first J update. Gauge: `jobs.firstFrameMs`. */
  jobsFirstFrame: new Ring(64),
  /** Phase 11: a job's first J frame received on the socket to the frame that paints it (no network in it). */
  jobsFrameToPaint: new Ring(64),
  /** Phase 12: `BT` command submit to the painted labelled result (cached run: no simulation in it). */
  btOpen: new Ring(64),
};
export type SeriesName = keyof typeof series;

/** Last-value gauges set by subsystems (ws msgs/s, cache hit rate, provider latency...). Absent = not available yet. */
export const gauges = new Map<string, number>();

/** Per-panel React render cost (Profiler actualDuration). */
export const panelRender = new Map<number, Ring>();

export let longTasks = 0;

/** Command log ring: performance.measure results, newest last. */
export const commandLog: { cmd: string; ms: number; at: number }[] = [];

export function recordPanelRender(panelId: number, ms: number): void {
  let r = panelRender.get(panelId);
  if (!r) panelRender.set(panelId, (r = new Ring(64)));
  r.push(ms);
}

/** Calls fn after the next frame has been painted (rAF runs before paint; a task queued from it runs after). */
export function afterPaint(fn: () => void): void {
  requestAnimationFrame(() => setTimeout(fn, 0));
}

// --- Command-to-paint: start on submit, end when the target panel reports its content painted.
const pending = new Map<number, { seq: number; cmd: string; t0: number }>();
const started = new Map<number, number>();
let seq = 0;

/** When the last command aimed at this panel was submitted (performance.now()), if any. */
export const commandStartedAt = (panelId: number): number | undefined => started.get(panelId);

export function commandStart(panelId: number, cmd: string): void {
  seq++;
  performance.mark(`cmd:${seq}:start`);
  const t0 = performance.now();
  pending.set(panelId, { seq, cmd, t0 });
  started.set(panelId, t0);
}

export function panelPainted(panelId: number): void {
  const p = pending.get(panelId);
  if (!p) return;
  pending.delete(panelId);
  afterPaint(() => {
    const ms = performance.now() - p.t0;
    try {
      performance.measure(`cmd:${p.seq}`, `cmd:${p.seq}:start`);
      performance.clearMarks(`cmd:${p.seq}:start`);
      performance.clearMeasures(`cmd:${p.seq}`);
    } catch {
      /* marks may be cleared by the browser's buffer limit */
    }
    series.cmdToPaint.push(ms);
    commandLog.push({ cmd: p.cmd, ms, at: Date.now() });
    if (commandLog.length > 200) commandLog.shift();
  });
}

// --- Keystroke echo: keydown timestamp to the start of the frame that draws the character.
// The native input has already updated its value by then, so that frame paints it. We use the
// rAF timestamp (frame start), not performance.now() inside the callback: other callbacks in the
// same frame (tick flushes) would otherwise be billed to the keystroke.
let lastKeyDown = 0;
export function keyDown(ts: number): void {
  lastKeyDown = ts;
}
export function keyEchoed(): void {
  const t0 = lastKeyDown;
  if (!t0) return;
  lastKeyDown = 0;
  requestAnimationFrame((frameStart) => series.keyEcho.push(Math.max(0, frameStart - t0)));
}

// --- Frame sampler: runs only while someone watches (HUD, PERF panel, bench).
let watchers = 0;
let rafId = 0;
let lastFrame = 0;
let framesThisSec = 0;
let secStart = 0;
export let fps = NaN;

function frameLoop(t: number): void {
  if (lastFrame) series.frame.push(t - lastFrame);
  lastFrame = t;
  framesThisSec++;
  if (t - secStart >= 1000) {
    fps = (framesThisSec * 1000) / (t - secStart);
    framesThisSec = 0;
    secStart = t;
  }
  rafId = requestAnimationFrame(frameLoop);
}

export function watchFrames(): () => void {
  if (watchers++ === 0) {
    lastFrame = 0;
    secStart = performance.now();
    framesThisSec = 0;
    rafId = requestAnimationFrame(frameLoop);
  }
  return () => {
    if (--watchers === 0) {
      cancelAnimationFrame(rafId);
      fps = NaN;
    }
  };
}

export function heapMB(): number {
  const m = (performance as unknown as { memory?: { usedJSHeapSize: number } }).memory;
  return m ? m.usedJSHeapSize / 1048576 : NaN;
}

export function installObservers(): void {
  try {
    new PerformanceObserver((list) => {
      longTasks += list.getEntries().length;
    }).observe({ type: "longtask", buffered: true });
  } catch {
    /* longtask API is Chromium-only */
  }
}

export function snapshot() {
  const s = (r: Ring) => ({ n: r.size, last: r.last(), p50: r.percentile(50), p95: r.percentile(95) });
  return {
    fps,
    frameP95: series.frame.percentile(95),
    longTasks,
    heapMB: heapMB(),
    keyEcho: s(series.keyEcho),
    cmdToPaint: s(series.cmdToPaint),
    tickToPixel: s(series.tickToPixel),
    wsRtt: s(series.wsRtt),
    layoutLoad: s(series.layoutLoad),
    jobsFirstFrame: s(series.jobsFirstFrame),
    jobsFrameToPaint: s(series.jobsFrameToPaint),
    btOpen: s(series.btOpen),
    gauges: Object.fromEntries(gauges),
    panels: Object.fromEntries([...panelRender].map(([id, r]) => [id, r.percentile(95)])),
  };
}

/** Clears every measurement window (bench uses it between scenarios). */
export function reset(): void {
  for (const r of Object.values(series)) r.clear();
  panelRender.clear();
  longTasks = 0;
  commandLog.length = 0;
}

declare global {
  interface Window {
    __openterm_perf?: { snapshot: typeof snapshot; watchFrames: typeof watchFrames; reset: typeof reset; commandLog: typeof commandLog; ready?: number };
  }
}
window.__openterm_perf = { snapshot, watchFrames, reset, commandLog };
