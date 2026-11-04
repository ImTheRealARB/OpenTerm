import { panelGone } from "../state/panelGone";
import { workspace } from "../state/workspace";

/**
 * Calls `onGone` once if panel `panelId` is closed (or switched to another function)
 * while it runs a paid stream. Returns the unsubscribe: call it when the stream ends.
 * The watch lives with the stream, not the React component, so a maximize remount
 * neither stops the stream nor loses the ability to stop it on close.
 */
export function watchPanelGone(panelId: number, onGone: () => void): () => void {
  const p = workspace.get().panels[panelId];
  const fn = p?.views[p.pos]?.fn; // the function this stream belongs to
  const off = workspace.subscribe(() => {
    if (panelGone(workspace.get(), panelId, fn)) {
      off();
      onGone();
    }
  });
  return off;
}
