import { gauges, series } from "../perf/metrics";
import { createStore } from "../state/store";
import { ingest } from "../state/ticks";
import { heartbeatDead, heartbeatMissed } from "./heartbeat";
import { ingestJobFrame } from "./jobs";

export interface LinkState {
  status: "CONNECTING" | "OK" | "DOWN";
  rttMs: number;
  lastMsgAt: number;
}

export const link = createStore<LinkState>({ status: "CONNECTING", rttMs: NaN, lastMsgAt: 0 });

/** Symbol -> number of panels/components subscribed. The server sees one subscription per symbol. */
const refs = new Map<string, number>();
let socket: WebSocket | null = null;
let frames = 0;

function send(msg: unknown): void {
  if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(msg));
}

/** Subscribe to live ticks. Returns the matching unsubscribe. Safe to call before the socket opens. */
export function subscribe(symbols: string[]): () => void {
  const added: string[] = [];
  for (const s of symbols) {
    const n = (refs.get(s) ?? 0) + 1;
    refs.set(s, n);
    if (n === 1) added.push(s);
  }
  if (added.length) send(["sub", added]);
  let done = false;
  return () => {
    if (done) return;
    done = true;
    const removed: string[] = [];
    for (const s of symbols) {
      const n = (refs.get(s) ?? 1) - 1;
      if (n <= 0) {
        refs.delete(s);
        removed.push(s);
      } else refs.set(s, n);
    }
    if (removed.length) send(["unsub", removed]);
  };
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
      if (refs.size) send(["sub", [...refs.keys()]]);
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
