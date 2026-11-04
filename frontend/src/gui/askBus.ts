/**
 * A panel (for example an empty watchlist) can ask the GUI toolbar to open one of its "ask" boxes, such as the
 * "Add" box of a watchlist. The panel and the toolbar are different components, so they talk through one window
 * event: the panel calls `requestAsk(panelId, "Add")`, the toolbar of that panel opens the box of its button
 * with that label (`PanelToolbar` listens). Nothing happens in Terminal mode (there is no toolbar to hear it).
 */
const EVENT = "openterm:ask";

export interface AskRequest {
  panelId: number;
  /** Label of the toolbar button whose box should open, e.g. "Add". */
  label: string;
}

export function requestAsk(panelId: number, label: string): void {
  window.dispatchEvent(new CustomEvent<AskRequest>(EVENT, { detail: { panelId, label } }));
}

/** Calls `fn` for every request until the returned function is called. */
export function onAskRequest(fn: (r: AskRequest) => void): () => void {
  const h = (e: Event) => fn((e as CustomEvent<AskRequest>).detail);
  window.addEventListener(EVENT, h);
  return () => window.removeEventListener(EVENT, h);
}
