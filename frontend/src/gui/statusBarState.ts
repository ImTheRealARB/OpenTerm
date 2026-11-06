/**
 * Whether the bottom status bar (backend, data source, alert flashes) is shown in GUI mode.
 * Per-viewer convenience like the sidebar toggle, so it lives in localStorage, not in the synced settings.
 * Default: HIDDEN in GUI mode (it reads as noise to a beginner). Terminal mode always shows it.
 */
import { persistedFlag } from "../state/persistedFlag";

const shown = persistedFlag("openterm.statusBarShown", false);

/** React hook: true while the user has switched the GUI status bar on. */
export function useStatusBarShown(): boolean {
  return shown.useValue();
}

export const toggleStatusBar = shown.toggle;
