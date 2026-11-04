/**
 * GUI "tabs" layout: one panel fills the workspace and a strip of tabs (like a browser) switches between the open panels.
 * Off = the tiled layout (several panels side by side). Per-viewer convenience, so it lives in localStorage and not in the
 * synced settings. Default: on, so a new GUI user is not handed a screen cut into tiles.
 */
import { createStore, useStore } from "../state/store";

const KEY = "openterm.guiTabs";

function load(): boolean {
  try {
    return localStorage.getItem(KEY) !== "0"; // only an explicit "0" turns tabs off
  } catch {
    return true; // storage blocked: behave as the default
  }
}

const on = createStore<boolean>(typeof localStorage === "undefined" ? true : load());

/** React hook: true while the GUI uses tabs instead of tiles. (The caller also checks GUI mode: terminal mode never uses tabs.) */
export function useTabsOn(): boolean {
  return useStore(on, (s) => s);
}

export function setTabs(value: boolean): void {
  on.set(() => value);
  try {
    localStorage.setItem(KEY, value ? "1" : "0");
  } catch {
    /* not persisted; the switch still works for this page load */
  }
}
