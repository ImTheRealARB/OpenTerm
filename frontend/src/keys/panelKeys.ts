/**
 * Panel-local keyboard handlers (grid j/k, chart 1..8, ...). The focused panel gets first shot at
 * unmodified keys; anything it doesn't handle falls through to global bindings / type-to-command.
 */
export type PanelKeyHandler = (e: KeyboardEvent) => boolean;

const handlers = new Map<number, PanelKeyHandler[]>();

export function registerPanelKeys(panelId: number, h: PanelKeyHandler): () => void {
  const list = handlers.get(panelId) ?? [];
  list.push(h);
  handlers.set(panelId, list);
  return () => {
    const l = handlers.get(panelId);
    if (!l) return;
    const i = l.indexOf(h);
    if (i >= 0) l.splice(i, 1);
  };
}

/** Most recently registered handler first (an open overlay inside a panel wins over the panel). */
export function dispatchPanelKey(panelId: number, e: KeyboardEvent): boolean {
  const list = handlers.get(panelId);
  if (!list) return false;
  for (let i = list.length - 1; i >= 0; i--) if (list[i](e)) return true;
  return false;
}
