/**
 * A true/false switch that survives a page reload by living in localStorage under `key` (stored as "1" / "0").
 * For per-viewer conveniences (sidebar hidden, tabs on, status bar shown), not for settings that sync between devices.
 *
 * Storage can be missing or blocked (private window, a Node test run): every access is wrapped in try/catch, the switch then
 * starts at `defaultValue`, and a change still works for this page load, it just is not remembered.
 * Anything stored other than "1" or "0" counts as unset and gives `defaultValue`.
 */
import { createStore, useStore } from "./store";

export interface PersistedFlag {
  /** React hook: the current value; the component re-renders when it changes. */
  useValue: () => boolean;
  /** The current value, for code outside React (and for tests). */
  get: () => boolean;
  /** Sets the value and remembers it. */
  set: (value: boolean) => void;
  /** Flips the value and remembers it. */
  toggle: () => void;
}

export function persistedFlag(key: string, defaultValue: boolean): PersistedFlag {
  const read = (): boolean => {
    try {
      if (typeof localStorage === "undefined") return defaultValue;
      const stored = localStorage.getItem(key);
      return stored === "1" ? true : stored === "0" ? false : defaultValue;
    } catch {
      return defaultValue; // storage blocked
    }
  };
  const flag = createStore<boolean>(read());
  const set = (value: boolean): void => {
    flag.set(() => value);
    try {
      localStorage.setItem(key, value ? "1" : "0");
    } catch {
      /* not persisted; the switch still works for this page load */
    }
  };
  return {
    useValue: () => useStore(flag, (s) => s),
    get: () => flag.get(),
    set,
    toggle: () => set(!flag.get()),
  };
}
