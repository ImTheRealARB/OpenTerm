/**
 * Settings in the running app. Cold start applies the localStorage mirror synchronously (before the first
 * render, so the theme never flashes); `settings/sync.ts` reconciles with the backend after the first paint,
 * the same way the live workspace works. No `net/api` import here: Grid and charts read `displayVersion`.
 */
import { setNumberFormat } from "../format";
import { setKeyOverrides } from "../keys/keys";
import { createStore, loadJSON, saveJSON } from "../state/store";
import { DEFAULTS, diffFromDefaults, normalize, type PollKey, type Settings } from "./schema";
import { applyTheme } from "./themes";

const MIRROR = "openterm.settings";

interface Mirror {
  settings: Partial<Settings>;
  /** Backend `updated_at` of the copy we hold, or local time of an unsynced edit (epoch seconds). */
  updatedAt: number;
  /** Changed locally and not yet stored by the backend. */
  dirty: boolean;
}

const mirror: Mirror = (() => {
  const m = loadJSON<Partial<Mirror> | null>(MIRROR, null);
  return { settings: m?.settings ?? {}, updatedAt: typeof m?.updatedAt === "number" ? m.updatedAt : 0, dirty: m?.dirty === true };
})();

export const settingsStore = createStore<Settings>(normalize(mirror.settings).settings);
/** Bumped when anything canvas code caches changes (theme colours, number format). Grid/charts redraw on it. */
export const displayVersion = createStore(0);

let applied: Settings | null = null;
let onLocalChange: (() => void) | null = null;

function apply(next: Settings): void {
  const prev = applied;
  applied = next;
  let display = false;
  if (!prev || prev.theme !== next.theme) {
    if (typeof document !== "undefined") applyTheme(next.theme, document.documentElement);
    display = true;
  }
  if (!prev || prev.numberFormat.thousands !== next.numberFormat.thousands || prev.numberFormat.decimal !== next.numberFormat.decimal) {
    setNumberFormat(next.numberFormat.thousands, next.numberFormat.decimal);
    display = true;
  }
  if (!prev || JSON.stringify(prev.keys) !== JSON.stringify(next.keys)) setKeyOverrides(next.keys);
  if (display && prev) displayVersion.set((v) => v + 1);
}

/** Cold start: apply the mirror before React renders. */
export function initSettings(): void {
  apply(settingsStore.get());
  settingsStore.subscribe(() => apply(settingsStore.get()));
}

export const getSettings = (): Settings => settingsStore.get();
export const pollMs = (key: PollKey): number => settingsStore.get().poll[key] * 1000;

function persist(): void {
  saveJSON(MIRROR, mirror);
}

/** A user edit: applies at once, mirrors locally, and asks sync.ts to store it on the backend. */
export function updateSettings(fn: (s: Settings) => Settings): Settings {
  const next = normalize(diffFromDefaults(fn(settingsStore.get()))).settings;
  mirror.settings = diffFromDefaults(next);
  mirror.updatedAt = Date.now() / 1000;
  mirror.dirty = true;
  persist();
  settingsStore.set(() => next);
  onLocalChange?.();
  return next;
}

export function resetSettings(): Settings {
  return updateSettings(() => ({ ...DEFAULTS, keys: {} }));
}

// --- used by sync.ts ---------------------------------------------------------------------
export const mirrorState = (): Readonly<Mirror> => mirror;

export function setLocalChangeListener(fn: () => void): void {
  onLocalChange = fn;
}

/** Backend copy wins (startup reconcile). */
export function adoptRemote(raw: unknown, updatedAt: number): void {
  const next = normalize(raw).settings;
  mirror.settings = diffFromDefaults(next);
  mirror.updatedAt = updatedAt;
  mirror.dirty = false;
  persist();
  settingsStore.set(() => next);
}

/** The backend stored our copy. Edits made while the request was in flight stay dirty. */
export function markSynced(sent: string, updatedAt: number): void {
  if (JSON.stringify(mirror.settings) !== sent) return;
  mirror.updatedAt = updatedAt;
  mirror.dirty = false;
  persist();
}
