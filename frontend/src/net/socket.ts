import { series } from "../perf/metrics";
import { createStore } from "../state/store";

export interface LinkState {
  status: "CONNECTING" | "OK" | "DOWN";
  rttMs: number;
  lastMsgAt: number;
}

export const link = createStore<LinkState>({ status: "CONNECTING", rttMs: NaN, lastMsgAt: 0 });

/**
 * One multiplexed socket for the whole app. Phase 1 carries ping/pong for link health;
 * subscribe/unsubscribe arrives in phase 3. Frames are compact JSON arrays.
 */
export function connect(): void {
  let backoff = 500;
  let pingTimer = 0;

  const open = () => {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws`);
    const ping = () => ws.readyState === 1 && ws.send(JSON.stringify(["ping", performance.now()]));

    ws.onopen = () => {
      backoff = 500;
      ping();
      pingTimer = window.setInterval(ping, 5000);
    };
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data as string) as unknown[];
      if (msg[0] === "pong") {
        const rtt = performance.now() - (msg[1] as number);
        series.wsRtt.push(rtt);
        link.set((s) => ({ ...s, status: "OK", rttMs: rtt, lastMsgAt: Date.now() }));
      }
    };
    ws.onclose = () => {
      clearInterval(pingTimer);
      link.set((s) => ({ ...s, status: "DOWN" }));
      setTimeout(open, backoff);
      backoff = Math.min(backoff * 2, 15000);
    };
  };
  open();
}
