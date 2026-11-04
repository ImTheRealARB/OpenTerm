/**
 * Whether the bottom status bar (backend, data source, alert flashes) is shown in GUI mode.
 * Per-viewer convenience like the sidebar toggle, so it lives in localStorage, not in the synced settings.
 * Default: HIDDEN in GUI mode (it reads as noise to a beginner). Terminal mode always shows it.
 */
import { createStore, useStore } from "../state/store";

const KEY = "openterm.statusBarShown";

function load(): boolean {
  try {
    return localStorage.getItem(KEY) === "1";
  } catch {
    return false; // storage blocked (private window): behave as "hidden"
  }
}

const shown = createStore<boolean>(typeof localStorage === "undefined" ? false : load());

/** React hook: true while the user has switched the GUI status bar on. */
export function useStatusBarShown(): boolean {
  return useStore(shown, (s) => s);
}

export function toggleStatusBar(): void {
  shown.set((s) => !s);
  try {
    localStorage.setItem(KEY, shown.get() ? "1" : "0");
  } catch {
    /* not persisted; the toggle still works for this page load */
  }
}
