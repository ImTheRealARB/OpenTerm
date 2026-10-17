/**
 * Alerts (`ALRT`): stored in SQLite by the backend, evaluated here on every live tick.
 *
 * The monitor starts at boot and subscribes (through the shared refcounted socket) to the symbols of active
 * alerts, whether or not an ALRT panel is open. Ticks are checked as they arrive (`onRawTicks`), not in the
 * animation-frame flush, so a hidden tab (rAF paused) still fires. An alert fires once: it is marked triggered
 * locally at once, then on the backend with the trigger price and time. A closed tab evaluates nothing.
 */
import { fmtPrice } from "../format";
import { api8, type Alert, type ApiError } from "../net/api";
import { subscribe } from "../net/socket";
import { createStore } from "../state/store";
import { onRawTicks } from "../state/ticks";
import { alertMet, describeRule, parseAlrt } from "./alertArgs";
import type { SecurityRef } from "./markets";
import { fail, info, statusMsg } from "./status";

export const alerts = createStore<Alert[] | null>(null);
export const alertsError = createStore<string | null>(null);
/** The last alert that fired, for the status bar flash. */
export const lastFired = createStore<{ text: string; at: number } | null>(null);

export type NotifyState = "granted" | "denied" | "default" | "unsupported";
const notifySupported = () => typeof Notification !== "undefined";
const readNotify = (): NotifyState => (notifySupported() ? (Notification.permission as NotifyState) : "unsupported");
export const notifyState = createStore<NotifyState>(readNotify());
/** The user may change the permission in the browser at any time: re-read it when the ALRT panel opens. */
export const refreshNotifyState = () => notifyState.set(() => readNotify());

const errText = (e: unknown) => (e as ApiError).message ?? String(e);
export const alertText = (a: Pick<Alert, "symbol" | "op" | "unit" | "value">) => `${a.symbol} ${describeRule(a)}`;

/** Alerts this tab fired whose backend update is pending (or failed): never fire twice. */
const firing = new Set<number>();
let unsub: (() => void) | null = null;
let subKey = "";

/** Keeps exactly one subscription set for the symbols of active alerts (new set first, so shared symbols never drop). */
function syncSubscriptions(list: Alert[]): void {
  const syms = [...new Set(list.filter((a) => a.status === "active").map((a) => a.symbol))].sort();
  const key = syms.join(",");
  if (key === subKey) return;
  const old = unsub;
  unsub = syms.length ? subscribe(syms) : null;
  subKey = key;
  old?.();
}

function setAlerts(list: Alert[]): void {
  alerts.set(() => list);
  syncSubscriptions(list);
}

export async function refreshAlerts(): Promise<Alert[]> {
  try {
    const { alerts: list } = await api8.alerts();
    // An alert this tab already fired stays triggered even if the backend has not stored it yet.
    const local = new Map((alerts.get() ?? []).map((a) => [a.id, a]));
    const merged = list.map((a) => (a.status === "active" && local.get(a.id)?.status === "triggered" && firing.has(a.id) ? local.get(a.id)! : a));
    setAlerts(merged);
    alertsError.set(() => null);
    return merged;
  } catch (e) {
    alertsError.set(() => errText(e));
    throw e;
  }
}

/** Asks once for desktop notifications. Must run inside the user's keypress (the ALRT command). */
function askNotifyPermission(): void {
  if (!notifySupported() || Notification.permission !== "default") return;
  try {
    void Notification.requestPermission().then((p) => notifyState.set(() => p as NotifyState), () => notifyState.set(() => "denied"));
  } catch {
    notifyState.set(() => "denied");
  }
}

function desktopNotify(title: string, body: string, tag: string): void {
  if (!notifySupported() || Notification.permission !== "granted") return;
  try {
    new Notification(title, { body, tag });
  } catch {
    /* some browsers only allow notifications from a service worker: the in-app flash still shows */
  }
}

function fire(a: Alert, price: number, src: string): void {
  firing.add(a.id);
  const at = Date.now() / 1000;
  setAlerts((alerts.get() ?? []).map((x) => (x.id === a.id ? { ...x, status: "triggered", trigger_price: price, triggered_at: at } : x)));
  const synthetic = src === "s" ? " (SYNTHETIC)" : "";
  const text = `ALERT ${a.id} ${alertText(a)} HIT ${fmtPrice(price)}${synthetic}`;
  lastFired.set(() => ({ text, at: Date.now() }));
  info(text);
  desktopNotify(`ALERT ${alertText(a)}`, `${a.symbol} ${fmtPrice(price)}${synthetic}`, `openterm-alert-${a.id}`);
  api8.triggerAlert(a.id, price, at).then(
    () => firing.delete(a.id),
    (e) => fail(`ALERT ${a.id} FIRED BUT NOT SAVED: ${errText(e)}`),
  );
}

function onTicksForAlerts(rows: readonly (readonly unknown[])[]): void {
  const list = alerts.get();
  if (!list?.length) return;
  for (const r of rows) {
    const sym = r[0] as string;
    for (const a of list) {
      if (a.status !== "active" || a.symbol !== sym || firing.has(a.id)) continue;
      if (alertMet(a, r[1] as number, r[3] as number | null, r[2] as number | null)) fire(a, r[1] as number, r[8] as string);
    }
  }
}

let started = false;

/** Boot: load alerts, subscribe their symbols, watch ticks. Re-syncs every minute (other tabs, restarts). */
export function startAlerts(): void {
  if (started) return;
  started = true;
  onRawTicks(onTicksForAlerts);
  void refreshAlerts().catch(() => {});
  setInterval(() => void refreshAlerts().catch(() => {}), 60_000);
}

async function act(what: string, call: () => Promise<unknown>, ok: string): Promise<boolean> {
  try {
    await call();
  } catch (e) {
    void refreshAlerts().catch(() => {});
    return fail(`${what}: ${errText(e)}`);
  }
  info(ok);
  await refreshAlerts().catch(() => {});
  return true;
}

export const deleteAlert = (id: number) => act(`ALERT ${id} NOT DELETED`, () => api8.deleteAlert(id), `ALERT ${id} DELETED`);
export const rearmAlert = (id: number) => {
  firing.delete(id);
  return act(`ALERT ${id} NOT REARMED`, () => api8.rearmAlert(id), `ALERT ${id} REARMED`);
};
export const clearAlerts = () => act("ALERTS NOT CLEARED", () => api8.clearAlerts(), "TRIGGERED ALERTS CLEARED");

/** Runs an `ALRT ...` command. true/false = finished here; string[] = show `ALRT <args>`. */
export function alrtCommand(args: string[], security?: SecurityRef): boolean | string[] {
  const a = parseAlrt(args, security);
  switch (a.kind) {
    case "error":
      return fail(a.message);
    case "list":
      return [];
    case "delete":
      statusMsg.set(() => null);
      void deleteAlert(a.id);
      return [];
    case "rearm":
      void rearmAlert(a.id);
      return [];
    case "clear":
      void clearAlerts();
      return [];
    case "create": {
      askNotifyPermission(); // synchronously, inside the keypress that ran the command
      const text = alertText({ symbol: a.symbol, ...a.rule });
      void act(`ALERT ${text} NOT SAVED`, () => api8.createAlert({ symbol: a.symbol, ...a.rule }), `ALERT SET: ${text}`);
      return [];
    }
  }
}
