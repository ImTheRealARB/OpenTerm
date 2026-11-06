import type { PanelState, View } from "./workspace";

/**
 * Has this panel really gone away, or moved on to another view?
 *
 * Maximizing or restoring a panel REMOUNTS its React component, so "the component
 * unmounted" cannot tell us the user closed it. The workspace state can. `view` is the
 * view OBJECT the stream was started from (`panel.views[panel.pos]`). The stream is stale when:
 *  - the panel is no longer in `panels` (it was closed), or
 *  - the panel's current view is not that same object any more: a typed command
 *    (`navigate`), Alt+Left/Right history (`historyGo`), a layout load, or `replaceView`
 *    all produce a different object, even when the function code stays `AI` / `SWARM`.
 * `maximized` / `focus` only change how the panel is drawn and keep the same view
 * object, so they never abort a running stream.
 */
export function panelGone(s: { panels: Record<number, PanelState> }, id: number, view: View | undefined): boolean {
  const p = s.panels[id];
  if (!p) return true;
  return p.views[p.pos] !== view;
}
