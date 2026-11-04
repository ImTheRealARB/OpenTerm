/**
 * Alerts (`ALRT`): stored in SQLite by the backend, evaluated here on every live tick.
 *
 * The monitor starts at boot and subscribes (through the shared refcounted socket) to the symbols of active
 * alerts, whether or not an ALRT panel is open. Ticks are checked as they arrive (`onRawTicks`), not in the
 * animation-frame flush, so a hidden tab (rAF paused) still fires. An alert fires once: it is marked triggered
 * locally at once, then on the backend with the trigger price and time. A closed tab evaluates nothing.
 */
import { fmtPrice } from "../format";
import { api, api8, newsAlertsApi, type Alert, type ApiError, type NewsAlert, type NewsItem } from "../net/api";
import { subscribe } from "../net/socket";
import { createStore } from "../state/store";
import { onRawTicks } from "../state/ticks";
import { sendWithRetry } from "./triggerRetry";
import { alertMet, describeRule, newsMatch, parseAlrt } from "./alertArgs";
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
  // The id stays in `firing` until the backend accepts the report, so the tick check cannot fire it twice; a failed POST
  // is retried with backoff while the alert is still firing and still exists (re-arm or delete ends the retries).
  sendWithRetry(() => api8.triggerAlert(a.id, price, at), {
    stillWanted: () => firing.has(a.id) && (alerts.get() ?? []).some((x) => x.id === a.id),
    onDone: () => firing.delete(a.id),
    onFail: (e, n) => {
      if (n === 1) fail(`ALERT ${a.id} FIRED BUT NOT SAVED, RETRYING: ${errText(e)}`);
    },
  });
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

// --- Phase 13: news keyword alerts (ALRT NEWS WORD [SYM]) --------------------------------------------------------------
// Checked whenever a news answer arrives: the N panel reports its items (`checkNewsItems`), and a background poll fetches
// the headlines of each watched symbol (or the market top stories) every 2 minutes while an alert is active. A headline
// fires an alert only if it was published after the alert was created or re-armed, so old news never fires.
export const newsAlerts = createStore<NewsAlert[] | null>(null);
const newsFiring = new Set<number>();
export const NEWS_POLL_MS = 120_000;

/** Loads the news alerts. A failure throws and leaves the list as it was: an outage already shows through `refreshAlerts`. */
export async function refreshNewsAlerts(): Promise<NewsAlert[]> {
  const { alerts: list } = await newsAlertsApi.list();
  const local = new Map((newsAlerts.get() ?? []).map((a) => [a.id, a]));
  newsAlerts.set(() => list.map((a) => (a.status === "active" && newsFiring.has(a.id) && local.get(a.id) ? local.get(a.id)! : a)));
  return list;
}

function fireNews(a: NewsAlert, item: NewsItem): void {
  newsFiring.add(a.id);
  const at = Date.now() / 1000;
  newsAlerts.set((cur) =>
    (cur ?? []).map((x) => (x.id === a.id ? { ...x, status: "triggered", triggered_at: at, headline: item.title, url: item.url } : x)),
  );
  const where = a.symbol ?? "MARKET";
  const text = `NEWS ALERT N${a.id} ${where} "${a.word}": ${item.title}`;
  lastFired.set(() => ({ text, at: Date.now() }));
  info(text);
  desktopNotify(`NEWS ${where} ${a.word}`, item.title, `openterm-news-alert-${a.id}`);
  // Same retry as price alerts: keep the id in `newsFiring` until the backend accepts the report.
  sendWithRetry(() => newsAlertsApi.trigger(a.id, item.title, item.url, at), {
    stillWanted: () => newsFiring.has(a.id) && (newsAlerts.get() ?? []).some((x) => x.id === a.id),
    onDone: () => newsFiring.delete(a.id),
    onFail: (e, n) => {
      if (n === 1) fail(`NEWS ALERT N${a.id} FIRED BUT NOT SAVED, RETRYING: ${errText(e)}`);
    },
  });
}

/** Checks fetched headlines against the active news alerts for `symbol` (null = market top stories). */
export function checkNewsItems(symbol: string | null, items: readonly NewsItem[]): void {
  const list = newsAlerts.get();
  if (!list?.length) return;
  for (const a of list) {
    if (a.status !== "active" || newsFiring.has(a.id) || (a.symbol ?? null) !== symbol) continue;
    const hit = items.find((i) => i.published != null && i.published > a.created_at && newsMatch(a.word, i.title));
    if (hit) fireNews(a, hit);
  }
}

let newsPolling = false;

/** Fetches the headlines every active news alert watches (one request per distinct symbol) and checks them. */
export async function pollNewsAlerts(): Promise<void> {
  if (newsPolling) return;
  const active = (newsAlerts.get() ?? []).filter((a) => a.status === "active");
  if (!active.length) return;
  newsPolling = true;
  try {
    for (const symbol of [...new Set(active.map((a) => a.symbol))]) {
      try {
        const env = await api.news(symbol ? { symbol } : {});
        checkNewsItems(symbol, env.data.items);
      } catch {
        /* a news outage is shown by N; the alert simply waits for the next poll */
      }
    }
  } finally {
    newsPolling = false;
  }
}

let started = false;

/** Boot: load alerts, subscribe their symbols, watch ticks. Re-syncs every minute (other tabs, restarts). */
export function startAlerts(): void {
  if (started) return;
  started = true;
  onRawTicks(onTicksForAlerts);
  void refreshAlerts().catch(() => {});
  void refreshNewsAlerts().then(() => pollNewsAlerts()).catch(() => {});
  setInterval(() => void refreshAlerts().catch(() => {}), 60_000);
  setInterval(() => void refreshNewsAlerts().catch(() => {}), 60_000);
  setInterval(() => void pollNewsAlerts(), NEWS_POLL_MS);
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
export const clearAlerts = () =>
  act("ALERTS NOT CLEARED", () => api8.clearAlerts(), "TRIGGERED ALERTS CLEARED").then(async (ok) => {
    // Triggered news keyword alerts go with them; that list failing to clear is not worth failing the command for.
    if (ok) await newsAlertsApi.clear().catch(() => {});
    void refreshNewsAlerts().catch(() => {});
    return ok;
  });

/** News keyword alerts (ids shown as N<id>). */
export const deleteNewsAlert = (id: number) =>
  act(`NEWS ALERT N${id} NOT DELETED`, () => newsAlertsApi.delete(id), `NEWS ALERT N${id} DELETED`).then((ok) => (void refreshNewsAlerts().catch(() => {}), ok));
export const rearmNewsAlert = (id: number) => {
  newsFiring.delete(id);
  return act(`NEWS ALERT N${id} NOT REARMED`, () => newsAlertsApi.rearm(id), `NEWS ALERT N${id} REARMED`).then((ok) => (void refreshNewsAlerts().catch(() => {}), ok));
};

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
      void (a.news ? deleteNewsAlert(a.id) : deleteAlert(a.id));
      return [];
    case "rearm":
      void (a.news ? rearmNewsAlert(a.id) : rearmAlert(a.id));
      return [];
    case "createNews": {
      askNotifyPermission();
      const where = a.symbol ?? "MARKET";
      void act(
        `NEWS ALERT ${where} "${a.word}" NOT SAVED`,
        () => newsAlertsApi.create({ word: a.word, symbol: a.symbol }),
        `NEWS ALERT SET: ${where} HEADLINE CONTAINS "${a.word}" (CHECKED ON EACH NEWS REFRESH, EVERY 2 MIN)`,
      ).then(() => refreshNewsAlerts().catch(() => {}));
      return [];
    }
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
