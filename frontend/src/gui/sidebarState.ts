/**
 * Whether the GUI sidebar is shown. It is a per-viewer convenience (like a remembered tab), so it lives in
 * localStorage and not in the synced settings document. Default: shown, so a new GUI user still sees "Start here".
 */
import { createStore, useStore } from "../state/store";

const KEY = "openterm.sidebarHidden";

function load(): boolean {
  try {
    return localStorage.getItem(KEY) === "1";
  } catch {
    return false; // storage blocked (private window): behave as "shown"
  }
}

const hidden = createStore<boolean>(typeof localStorage === "undefined" ? false : load());

/** React hook: true while the sidebar is hidden. */
export function useSidebarHidden(): boolean {
  return useStore(hidden, (s) => s);
}

export function toggleSidebar(): void {
  hidden.set((s) => !s);
  try {
    localStorage.setItem(KEY, hidden.get() ? "1" : "0");
  } catch {
    /* not persisted; the toggle still works for this page load */
  }
}
