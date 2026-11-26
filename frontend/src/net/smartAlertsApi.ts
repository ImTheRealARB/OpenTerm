/** Phase 27 smart alerts: indicator alerts (BT rule on completed daily bars) and drawing alerts (GP lines), server-side. */
import { send } from "./core";
import type { JobRec } from "./jobFrames";
import type { SmartAlert } from "./types";

export const smartAlertsApi = {
  list: () => send<{ indicator: SmartAlert[]; drawing: SmartAlert[]; every_min: number }>("GET", "/api/smartalerts"),
  addIndicator: (symbol: string, rule: string) => send<{ alert: SmartAlert; job: JobRec }>("POST", "/api/smartalerts/indicator", { symbol, rule }),
  addDrawing: (symbol: string, n?: number) => send<{ alert: SmartAlert }>("POST", "/api/smartalerts/drawing", { symbol, ...(n ? { n } : {}) }),
  delete: (id: string) => send<{ deleted: string }>("DELETE", `/api/smartalerts/${encodeURIComponent(id)}`),
};
