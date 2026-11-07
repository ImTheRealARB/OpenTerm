/**
 * Whether the GUI sidebar is shown. It is a per-viewer convenience (like a remembered tab), so it lives in
 * localStorage and not in the synced settings document. Default: shown, so a new GUI user still sees "Start here".
 */
import { persistedFlag } from "../state/persistedFlag";

const hidden = persistedFlag("openterm.sidebarHidden", false);

/** React hook: true while the sidebar is hidden. */
export function useSidebarHidden(): boolean {
  return hidden.useValue();
}

export const toggleSidebar = hidden.toggle;
