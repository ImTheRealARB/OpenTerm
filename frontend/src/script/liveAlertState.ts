/**
 * Live script alerts: the small shared state (stores and wording). No engine and no request layer in here, so the ALRT panel,
 * the alert runner and the sync step can all import it, and vitest can too.
 *
 * Script alerts are RUN BY THIS BROWSER while OpenTerm is open (the server only stores them). Every place that shows one says so.
 */
import { createStore } from "../state/store";
import type { ScriptAlert } from "../net/scriptsApi";

/** The words every script-alert surface carries: the alert is not checked while OpenTerm is closed. */
export const RUNS_WHILE_OPEN = "RUNS WHILE OPENTERM IS OPEN";

/** The stored alerts (null = not loaded yet). Written by `liveAlertSync.refreshScriptAlerts`. */
export const scriptAlerts = createStore<ScriptAlert[] | null>(null);
/** Why the last load or change failed, shown in ALRT as its own line (the list on screen is then the last good one). */
export const scriptAlertsError = createStore<string | null>(null);

/** What this tab knows about one alert's run: loading its data, running, or stopped with an error; and the last time it fired. */
export interface ScriptAlertRun {
  state: "loading" | "running" | "error";
  error?: string;
  /** Epoch seconds of the last firing and its message. */
  firedAt?: number;
  message?: string;
}
export const scriptAlertRuns = createStore<Record<number, ScriptAlertRun>>({});

/** Shallow-merge `patch` into one alert's run state. */
export function setRun(id: number, patch: ScriptAlertRun | Partial<ScriptAlertRun>): void {
  scriptAlertRuns.set((cur) => ({ ...cur, [id]: { ...(cur[id] ?? { state: "loading" }), ...patch } as ScriptAlertRun }));
}

/** The one-line text of an alert for lists: `AAPL RSI-CROSS "RSI down"` or `AAPL RSI-CROSS (ALERT CALLS)`. */
export function scriptAlertText(a: Pick<ScriptAlert, "symbol" | "script" | "cond">): string {
  return `${a.symbol} SCRIPT ${a.script} ${a.cond === null ? "ALERT() CALLS" : `COND "${a.cond}"`}`;
}
