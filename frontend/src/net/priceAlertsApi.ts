/** Price alerts (ALRT) and the backend alert engine that fires them. Uncached (`send`). News-word alerts are `newsAlertsApi`. */
import { send } from "./core";
import type { Alert, AlertEngineState } from "./types";

export const priceAlertsApi = {
  alerts: () => send<{ alerts: Alert[] }>("GET", "/api/alerts"),
  createAlert: (a: { symbol: string; op: ">" | "<"; unit: "price" | "pct"; value: number; channels?: string[] }) => send<Alert>("POST", "/api/alerts", a),
  deleteAlert: (id: number) => send<{ deleted: number }>("DELETE", `/api/alerts/${id}`),
  alertEngine: () => send<AlertEngineState>("GET", "/api/alerts/engine"),
  /** `synthetic` tells the server this firing came from labelled test data, so it is never pushed to Telegram or email. */
  triggerAlert: (id: number, price: number, at: number, synthetic = false) =>
    send<{ alert: Alert; changed: boolean }>("POST", `/api/alerts/${id}/trigger`, synthetic ? { price, at, synthetic: true } : { price, at }),
  rearmAlert: (id: number) => send<Alert>("POST", `/api/alerts/${id}/rearm`),
  clearAlerts: () => send<{ deleted: number }>("DELETE", "/api/alerts?status=triggered"),
};
