import type { PanelState } from "./workspace";

/**
 * Has this panel really gone away?
 *
 * Maximizing or restoring a panel REMOUNTS its React component, so "the component
 * unmounted" cannot tell us the user closed it. The workspace state can: a panel is
 * gone when its id is no longer in `panels` (it was closed), or when the same panel
 * now shows a different function (the user ran another command in it).
 * `maximized` is deliberately ignored: it only changes how the panel is drawn.
 */
export function panelGone(s: { panels: Record<number, PanelState> }, id: number, fn: string | undefined): boolean {
  const p = s.panels[id];
  if (!p) return true;
  return (p.views[p.pos]?.fn ?? undefined) !== fn;
}
