/**
 * CSV export for every table panel. A panel adopts it with ONE hook call:
 *
 *   useCsvExport(panelId, () => gridCsv("Q_AAPL", COLUMNS, rows));
 *
 * That registers the panel's current table with the global binding (Alt+X, `exportCsv` in keybindings.json) and,
 * unless `{ panelKey: false }` is passed, the plain `E` panel key. The getter runs only when the user exports, so
 * it always sees the latest rows, sort and filter; returning null means "nothing to export yet".
 */
import { useEffect, useRef } from "react";
import { info } from "../command/status";
import type { Column } from "../components/Grid";
import { downloadCsv } from "../csv";
import type { CsvCell } from "../csvText";
import { registerPanelKeys } from "../keys/panelKeys";

export interface CsvTable {
  /** File name without extension, e.g. "EQS_TECH". Sanitized on download. */
  name: string;
  header: string[];
  rows: CsvCell[][];
}

export type CsvGetter = () => CsvTable | null;

const getters = new Map<number, CsvGetter[]>();

/** Formatted cells exactly as the grid shows them (what you see is what you get). */
export function gridCsv<R>(name: string, columns: Column<R>[], rows: R[], extra?: { title: string; text: (r: R) => CsvCell }[]): CsvTable {
  const cols = [...columns.map((c) => ({ title: c.title, text: c.text as (r: R) => CsvCell })), ...(extra ?? [])];
  return { name, header: cols.map((c) => c.title), rows: rows.map((r) => cols.map((c) => c.text(r))) };
}

/** Lower-level registration (the hook uses it). Most recent registration for a panel wins. */
export function registerCsv(panelId: number, get: CsvGetter): () => void {
  const list = getters.get(panelId) ?? [];
  list.push(get);
  getters.set(panelId, list);
  return () => {
    const l = getters.get(panelId);
    const i = l?.indexOf(get) ?? -1;
    if (l && i >= 0) l.splice(i, 1);
  };
}

export const hasCsv = (panelId: number) => (getters.get(panelId)?.length ?? 0) > 0;

/** Exports the panel's current table. Returns false (and says so) when the panel has no table to export. */
export function exportPanelCsv(panelId: number): boolean {
  const list = getters.get(panelId);
  const get = list?.[list.length - 1];
  if (!get) {
    info("NOTHING TO EXPORT IN THIS PANEL");
    return false;
  }
  const t = get();
  if (!t || !t.rows.length) {
    info("NO ROWS TO EXPORT YET");
    return false;
  }
  const file = downloadCsv(t.name, t.header, t.rows);
  info(`EXPORTED ${t.rows.length} ROWS TO ${file}`);
  return true;
}

export function useCsvExport(panelId: number, get: CsvGetter, opts: { panelKey?: boolean } = {}): void {
  const latest = useRef(get);
  latest.current = get;
  const panelKey = opts.panelKey ?? true;
  useEffect(() => {
    const off = registerCsv(panelId, () => latest.current());
    const offKey = panelKey
      ? registerPanelKeys(panelId, (e) => {
          if (e.key !== "e" || e.ctrlKey || e.altKey || e.metaKey) return false;
          exportPanelCsv(panelId);
          return true;
        })
      : undefined;
    return () => {
      off();
      offKey?.();
    };
  }, [panelId, panelKey]);
}
