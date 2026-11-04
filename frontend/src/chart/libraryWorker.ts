/**
 * Message handler for library indicators and formulas, called from the indicator Web Worker.
 * No DOM, no worker globals: pure, so it is unit-tested directly. Wiring (3 lines in indicators.worker.ts):
 *
 *   import { handleLibrary, isLibraryMsg } from "./libraryWorker";
 *   ...inside self.onmessage, first line:
 *   if (isLibraryMsg(ev.data)) { const r = handleLibrary(ev.data); (self as unknown as Worker).postMessage(r.msg, r.transfer); return; }
 */
import { evaluateFormula } from "./formula";
import { findIndicator, resolveParams } from "./library/catalog";
import type { Cols } from "./library/types";

export interface LibraryItem {
  /** Caller's key for the result (e.g. the series id on the chart). */
  key: string;
  /** Catalog id (e.g. "RSI") ... */
  id?: string;
  params?: number[];
  /** ... or a formula. Exactly one of id / formula. */
  formula?: string;
}

export interface LibraryReq {
  type: "library";
  id: number;
  series: Cols;
  items: LibraryItem[];
}

export type LibraryItemResult =
  | { ok: true; outputs: string[]; pane: "price" | "lower"; data: Float64Array[] }
  | { ok: false; error: string; pos: number };

export interface LibraryRes {
  type: "library";
  id: number;
  results: Record<string, LibraryItemResult>;
  ms: number;
}

export const MAX_ITEMS = 20;

export function isLibraryMsg(m: unknown): m is LibraryReq {
  return typeof m === "object" && m !== null && (m as { type?: unknown }).type === "library";
}

export function handleLibrary(req: LibraryReq, now: () => number = () => Date.now()): { msg: LibraryRes; transfer: ArrayBuffer[] } {
  const t0 = now();
  const results: Record<string, LibraryItemResult> = {};
  const transfer: ArrayBuffer[] = [];
  for (const item of req.items.slice(0, MAX_ITEMS)) {
    let r: LibraryItemResult;
    if (item.formula !== undefined) {
      const f = evaluateFormula(item.formula, req.series);
      r = f.ok ? { ok: true, outputs: ["formula"], pane: "lower", data: [f.out] } : f;
    } else {
      const def = item.id ? findIndicator(item.id) : undefined;
      if (!def) r = { ok: false, error: `UNKNOWN INDICATOR ${item.id ?? ""}`.trim(), pos: 0 };
      else r = { ok: true, outputs: def.outputs, pane: def.pane, data: def.fn(req.series, resolveParams(def, item.params)) };
    }
    if (r.ok) for (const a of r.data) transfer.push(a.buffer as ArrayBuffer);
    results[item.key] = r;
  }
  return { msg: { type: "library", id: req.id, results, ms: now() - t0 }, transfer };
}
