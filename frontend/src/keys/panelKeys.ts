/**
 * Panel-local keyboard handlers (grid j/k, chart 1..8, ...). The focused panel gets first shot at
 * unmodified keys; anything it doesn't handle falls through to global bindings / type-to-command.
 */
export type PanelKeyHandler = (e: KeyboardEvent) => boolean;

/** Keys that are only a modifier being pressed (the keydown a browser sends first for Shift+R, Ctrl+K ...). */
const BARE_MODIFIERS = new Set(["Shift", "Control", "Alt", "Meta", "AltGraph", "CapsLock"]);

/**
 * The ONE chord guard for every panel key handler. A panel handler never sees:
 *  - a bare modifier keydown (Playwright's Shift+R sends a "Shift" keydown first, which a handler would misread), or
 *  - a Ctrl / Alt / Meta chord (Ctrl+K must always reach the command line; Alt+1..9 etc. belong to the global keys).
 * Shift alone is NOT a chord: Shift+R and "?" are ordinary panel keys. Pure (reads three booleans and `key`), so vitest can
 * test it without a browser.
 */
export function isPanelKey(e: Pick<KeyboardEvent, "key" | "ctrlKey" | "altKey" | "metaKey">): boolean {
  return !(e.ctrlKey || e.altKey || e.metaKey) && !BARE_MODIFIERS.has(e.key);
}

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
  if (!isPanelKey(e)) return false; // chords and bare modifiers bubble on (see isPanelKey)
  const list = handlers.get(panelId);
  if (!list) return false;
  for (let i = list.length - 1; i >= 0; i--) if (list[i](e)) return true;
  return false;
}
