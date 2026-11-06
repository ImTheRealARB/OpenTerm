/**
 * GUI "tabs" layout: one panel fills the workspace and a strip of tabs (like a browser) switches between the open panels.
 * Off = the tiled layout (several panels side by side). Per-viewer convenience, so it lives in localStorage and not in the
 * synced settings. Default: on, so a new GUI user is not handed a screen cut into tiles.
 */
import { persistedFlag } from "../state/persistedFlag";

const on = persistedFlag("openterm.guiTabs", true);

/** React hook: true while the GUI uses tabs instead of tiles. (The caller also checks GUI mode: terminal mode never uses tabs.) */
export function useTabsOn(): boolean {
  return on.useValue();
}

export const setTabs = on.set;
