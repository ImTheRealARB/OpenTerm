import { gauges, series } from "../perf/metrics";
import { createStore } from "../state/store";
import { symCount, symId, symName } from "../state/symbols";
import { ingest, setStreamUp } from "../state/ticks";
import { heartbeatDead, heartbeatMissed } from "./heartbeat";
import { ingestJobFrame } from "./jobs";

export interface LinkState {
  status: "CONNECTING" | "OK" | "DOWN";
  rttMs: number;
  lastMsgAt: number;
}

export const link = createStore<LinkState>({ status: "CONNECTING", rttMs: NaN, lastMsgAt: 0 });

/**
 * Subscription reference counts, one slot per interned symbol id (see state/symbols.ts): refs[id] = how many panels/components
 * subscribed to that symbol. A flat Int32Array instead of a Map<string, number>: no string hashing, and "is it subscribed?" is
 * `refs[id] > 0`. The server still sees one subscription per symbol (we send only on 0 -> 1 and 1 -> 0).
 */
let refs: Int32Array = new Int32Array(256);
let socket: WebSocket | null = null;
let frames = 0;

function send(msg: unknown): void {
  if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(msg));
}

/** Callbacks run when the backend pushes an "A" frame: its alert engine fired an alert (Phase 20), so lists should refresh. */
const alertFrameListeners = new Set<(kind: "price" | "news", id: number) => void>();
export function onAlertFrame(cb: (kind: "price" | "news", id: number) => void): void {
  alertFrameListeners.add(cb);
}

/** Subscribe to live ticks. Returns the matching unsubscribe. Safe to call before the socket opens. */
export function subscribe(symbols: string[]): () => void {
  // Subscribing is a cold path (when a panel's symbols change), so the small arrays here are fine.
  const idList = symbols.map(symId);
  const added: string[] = [];
  for (let i = 0; i < idList.length; i++) {
    const id = idList[i];
    if (id >= refs.length) refs = grown(refs, id + 1);
    if (++refs[id] === 1) added.push(symbols[i]);
  }
  if (added.length) send(["sub", added]);
  let done = false;
  return () => {
    if (done) return;
    done = true;
    const removed: string[] = [];
    for (let i = 0; i < idList.length; i++) {
      const id = idList[i];
      if (refs[id] > 0 && --refs[id] === 0) removed.push(symbols[i]);
    }
    if (removed.length) send(["unsub", removed]);
  };
}

function grown(a: Int32Array, n: number): Int32Array {
  const out = new Int32Array(Math.max(n, a.length * 2));
  out.set(a);
  return out;
}

/** Every symbol with at least one subscriber (used to resubscribe after a reconnect). */
function subscribedSymbols(): string[] {
  const out: string[] = [];
  for (let id = 0; id < refs.length && id < symCount(); id++) if (refs[id] > 0) out.push(symName(id));
  return out;
}

/**
 * One multiplexed socket for the whole app; reconnects with backoff and resubscribes.
 * Frames are compact JSON arrays (see backend/openterm/main.py).
 */
export function connect(): void {
  let backoff = 500;
  let pingTimer = 0;

  setInterval(() => {
    gauges.set("ws.msgsPerSec", frames);
    frames = 0;
  }, 1000);

  const open = () => {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws`);
    socket = ws;
    let closed = false;
    let lastPingAt = 0;
    let lastRecvAt = 0;
    let missed = 0;
    // Runs once per socket, from `close` or from the heartbeat below (a half-open connection never fires `close`).
    const handleClose = () => {
      if (closed) return;
      closed = true;
      clearInterval(pingTimer);
      if (socket === ws) socket = null;
      link.set((s) => ({ ...s, status: "DOWN" }));
      setStreamUp(false); // stored ticks are history now: rows fall back to their REST snapshot and its STALE label
      setTimeout(open, backoff);
      backoff = Math.min(backoff * 2, 15000);
    };
    const ping = () => {
      if (ws.readyState !== 1) return;
      missed = heartbeatMissed(missed, lastPingAt, lastRecvAt);
      if (heartbeatDead(missed)) {
        handleClose();
        ws.onclose = ws.onmessage = null;
        ws.close();
        return;
      }
      lastPingAt = performance.now();
      ws.send(JSON.stringify(["ping", lastPingAt]));
    };

    ws.onopen = () => {
      backoff = 500;
      const subs = subscribedSymbols();
      if (subs.length) send(["sub", subs]);
      ping();
      pingTimer = window.setInterval(ping, 5000);
    };
    ws.onmessage = (ev) => {
      const recv = performance.now();
      lastRecvAt = recv;
      frames++;
      const msg = JSON.parse(ev.data as string) as unknown[];
      if (msg[0] === "T") {
        ingest(msg[1] as Parameters<typeof ingest>[0], recv);
      } else if (msg[0] === "A") {
        for (const cb of alertFrameListeners) cb(msg[1] as "price" | "news", msg[2] as number); // Phase 20: the server fired an alert; this tab only shows the new state
      } else if (msg[0] === "J") {
        ingestJobFrame(msg); // Phase 11 job progress
      } else if (msg[0] === "pong") {
        const rtt = recv - (msg[1] as number);
        series.wsRtt.push(rtt);
        link.set((s) => ({ ...s, status: "OK", rttMs: rtt, lastMsgAt: Date.now() }));
      }
    };
    ws.onclose = handleClose;
  };
  open();
}
