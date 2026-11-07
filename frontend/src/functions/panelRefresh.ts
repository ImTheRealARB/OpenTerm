/**
 * Refresh for every panel. A panel adopts it with ONE hook call:
 *
 *   usePanelRefresh(panelId, () => load(true));
 *
 * The global `refresh` action (default key F5, rebindable in SETTINGS KEYS), the GUI Refresh button and the window
 * menu all call `refreshPanel(panelId)`, which runs the function the focused panel registered. Panels therefore never
 * look for the literal key "F5": if the user rebinds `refresh` to another key, every panel still refreshes.
 * (Same pattern as CSV export in tableExport.ts.)
 *
 * The function may return `false` to say "I have nothing to refresh right now" (e.g. a view with no data source);
 * then the next registered function is tried, and finally the caller says NOTHING TO REFRESH.
 */
import { useEffect, useRef } from "react";
import { info } from "../command/status";

export type RefreshFn = () => boolean | void;

const fns = new Map<number, RefreshFn[]>();

/** Lower-level registration (the hook uses it). The most recent registration is tried first, so an overlay inside a panel wins. */
export function registerRefresh(panelId: number, fn: RefreshFn): () => void {
  const list = fns.get(panelId) ?? [];
  list.push(fn);
  fns.set(panelId, list);
  return () => {
    const l = fns.get(panelId);
    const i = l?.indexOf(fn) ?? -1;
    if (l && i >= 0) l.splice(i, 1);
  };
}

/** Runs the panel's refresh. Returns false when the panel has nothing to refresh. */
export function refreshPanel(panelId: number): boolean {
  const list = fns.get(panelId);
  if (!list) return false;
  for (let i = list.length - 1; i >= 0; i--) if (list[i]() !== false) return true;
  return false;
}

/** `refreshPanel`, but tells the user when there was nothing to refresh (used by the key, the menu and the Refresh button). */
export function refreshPanelOrSay(panelId: number): void {
  if (!refreshPanel(panelId)) info("NOTHING TO REFRESH IN THIS PANEL");
}

/**
 * Registers `fn` as this panel's refresh for as long as the panel is mounted. `fn` is read through a ref, so it always
 * sees the latest state and props even though the registration happens only once.
 */
export function usePanelRefresh(panelId: number, fn: RefreshFn): void {
  const latest = useRef(fn);
  latest.current = fn;
  useEffect(() => {
    const off = registerRefresh(panelId, () => latest.current());
    return () => {
      off();
    };
  }, [panelId]);
}
