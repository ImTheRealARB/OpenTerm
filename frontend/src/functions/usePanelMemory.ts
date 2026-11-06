import { useCallback, useSyncExternalStore } from "react";
import { memGet, memSet, memSubscribe, pruneMemory } from "../state/panelMemory";
import { workspace } from "../state/workspace";

// Forget a panel's memory when the panel closes (or never shows that function). Registered once,
// when the first function that uses panel memory (AI, SWARM) is loaded.
workspace.subscribe(() => pruneMemory(workspace.get()));

/**
 * `useState` that survives a remount of the panel. Same shape as `useState`, plus the panel it
 * belongs to. The setter writes to the shared memory (not to one component instance), so a
 * stream started by an earlier instance of the panel keeps updating whatever instance is
 * mounted now. `initial` must be a stable value (a module constant or a primitive).
 */
export function usePanelMemory<T>(fn: string, panelId: number, slot: string, initial: T): [T, (next: T | ((prev: T) => T)) => void] {
  // Stable callbacks: React resubscribes whenever the subscribe function changes identity.
  const subscribe = useCallback((listener: () => void) => memSubscribe(fn, panelId, slot, initial, listener), [fn, panelId, slot, initial]);
  const snapshot = useCallback(() => memGet(fn, panelId, slot, initial), [fn, panelId, slot, initial]);
  const value = useSyncExternalStore(subscribe, snapshot);
  const set = useCallback((next: T | ((prev: T) => T)) => memSet(fn, panelId, slot, next), [fn, panelId, slot]);
  return [value, set];
}
