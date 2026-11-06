import { panelGone } from "../state/panelGone";
import { workspace } from "../state/workspace";

/**
 * Calls `onGone` once if panel `panelId` is closed, or its current view is replaced by another
 * one (a new command, history step or layout load), while it runs a paid stream. Returns the
 * unsubscribe: call it when the stream ends.
 * The watch lives with the stream, not the React component, so a maximize remount neither stops
 * the stream nor loses the ability to stop it on close.
 * Start the watch AFTER anything that rewrites the panel's own view (the `replaceView(... args: [])`
 * clean-up), or that rewrite would look like the user moving on and abort the stream.
 */
export function watchPanelGone(panelId: number, onGone: () => void): () => void {
  const p = workspace.get().panels[panelId];
  const view = p?.views[p.pos]; // the exact view object this stream belongs to
  const off = workspace.subscribe(() => {
    if (panelGone(workspace.get(), panelId, view)) {
      off();
      onGone();
    }
  });
  return off;
}
