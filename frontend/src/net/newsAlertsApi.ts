/** News keyword alerts (ALRT NEWS WORD [SYM]): stored by the backend, evaluated in the browser on each news refresh. Uncached (`send`). */
import { send } from "./core";
import type { NewsAlert } from "./types";

export const newsAlertsApi = {
  list: () => send<{ alerts: NewsAlert[] }>("GET", "/api/newsalerts"),
  create: (a: { word: string; symbol: string | null; channels?: string[] }) => send<NewsAlert>("POST", "/api/newsalerts", a),
  delete: (id: number) => send<{ deleted: number }>("DELETE", `/api/newsalerts/${id}`),
  trigger: (id: number, headline: string, url: string, at: number) =>
    send<{ alert: NewsAlert; changed: boolean }>("POST", `/api/newsalerts/${id}/trigger`, { headline, url, at }),
  rearm: (id: number) => send<NewsAlert>("POST", `/api/newsalerts/${id}/rearm`),
  clear: () => send<{ deleted: number }>("DELETE", "/api/newsalerts?status=triggered"),
};
