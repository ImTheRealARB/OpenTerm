/** Phase 27: SCAN, saved scans and index movers (MRR). Smart alerts are in smartAlertsApi.ts (loaded at startup). */
import { send } from "./core";
import type { ColsResult, MrrResult, ScanResult, ScanSaved, ScanTask } from "./types";

export const scanApi = {
  start: (body: { universe: string; rule: string; symbols?: string[] }) => send<ScanTask<ScanResult>>("POST", "/api/scan", body),
  task: (id: string) => send<ScanTask<ScanResult>>("GET", `/api/scan/task/${encodeURIComponent(id)}`),
  saved: () => send<{ saved: ScanSaved[] }>("GET", "/api/scan/saved"),
  save: (name: string, body: { universe: string; rule: string; daily: string | null }) =>
    send<ScanSaved>("PUT", `/api/scan/saved/${encodeURIComponent(name)}`, body),
  del: (name: string) => send<{ deleted: string }>("DELETE", `/api/scan/saved/${encodeURIComponent(name)}`),
  runSaved: (name: string) => send<{ task: string; sent: boolean; matched?: number; error?: string }>("POST", `/api/scan/saved/${encodeURIComponent(name)}/run`, {}),
  mrr: (universe: string, period: string) =>
    send<ScanTask<MrrResult>>("POST", `/api/mrr?universe=${encodeURIComponent(universe)}&period=${encodeURIComponent(period)}`, {}),
  // IMAP NIFTY: the index members and their industry (no weights or market caps in NSE's list).
  nifty: (index: string) =>
    send<{ index: string; rows: { symbol: string; name: string; industry: string }[]; source: string }>(
      "GET", `/api/scan/nifty?index=${encodeURIComponent(index)}`),
  mrrTask:(id: string) => send<ScanTask<MrrResult>>("GET", `/api/mrr/task/${encodeURIComponent(id)}`),
  // WL / Q indicator columns: a task like SCAN's, polled on the same task route.
  cols: (symbols: string[], cols: string) => send<ScanTask<ColsResult>>("POST", "/api/scan/cols", { symbols, cols }),
  colsTask: (id: string) => send<ScanTask<ColsResult>>("GET", `/api/scan/task/${encodeURIComponent(id)}`),
};
