/**
 * Settings in the running app. Cold start applies the localStorage mirror synchronously (before the first
 * render, so the theme never flashes); `settings/sync.ts` reconciles with the backend after the first paint,
 * the same way the live workspace works. No `net/core` (request layer) import here: Grid and charts read `displayVersion`.
 */
import { setNumberFormat } from "../format";
import { setKeyOverrides } from "../keys/keys";
import { createStore, loadJSON, saveJSON } from "../state/store";
import { DEFAULTS, diffFromDefaults, normalize, type Mode, type PollKey, type Settings } from "./schema";
import { applyFont } from "./font";
import { parseMirror, sameMirror, type Mirror } from "./mirror";
import { applyTheme } from "./themes";

const MIRROR = "openterm.settings";

const saved = loadJSON<Partial<Mirror> | null>(MIRROR, null);
const mirror: Mirror = {
  settings: saved?.settings ?? {},
  updatedAt: typeof saved?.updatedAt === "number" ? saved.updatedAt : 0,
  dirty: saved?.dirty === true,
};

// No mirror in localStorage at all = a brand-new user: pass `undefined` so `normalize` picks the default mode (gui).
// A mirror that exists (even an empty `{}`) is saved settings, and `normalize` reads a missing `mode` as terminal.
export const settingsStore = createStore<Settings>(normalize(saved ? mirror.settings : undefined).settings);
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
  if (!prev || prev.font !== next.font) {
    if (typeof document !== "undefined") applyFont(next.font, document.documentElement);
    display = true; // grids and charts cache the font string
  }
  if (!prev || prev.numberFormat.thousands !== next.numberFormat.thousands || prev.numberFormat.decimal !== next.numberFormat.decimal) {
    setNumberFormat(next.numberFormat.thousands, next.numberFormat.decimal);
    display = true;
  }
  // CSS scopes the GUI-only look with :root[data-mode="gui"], so the attribute must always be present.
  if ((!prev || prev.mode !== next.mode) && typeof document !== "undefined") document.documentElement.dataset.mode = next.mode;
  if (!prev || JSON.stringify(prev.keys) !== JSON.stringify(next.keys)) setKeyOverrides(next.keys);
  if (display && prev) displayVersion.set((v) => v + 1);
}

/** Cold start: apply the mirror before React renders. */
export function initSettings(): void {
  apply(settingsStore.get());
  settingsStore.subscribe(() => apply(settingsStore.get()));
  // A bundled font downloads the first time something draws with it. DOM text swaps by itself, but canvas grids and charts
  // already drew with the fallback, so redraw them when any font finishes loading.
  if (typeof document !== "undefined" && document.fonts) document.fonts.addEventListener("loadingdone", () => displayVersion.set((v) => v + 1));
  // Another OpenTerm tab saved settings: take them, or this tab's next edit would overwrite them with its stale copy.
  if (typeof window !== "undefined") {
    window.addEventListener("storage", (e) => {
      if (e.key === MIRROR && e.storageArea === window.localStorage) adoptFromOtherTab(e.newValue);
    });
  }
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

/** Reset everything except the shell: a reset must not throw a terminal user into GUI mode (or the reverse). */
export function resetSettings(): Settings {
  return updateSettings((cur) => ({ ...DEFAULTS, mode: cur.mode, keys: {} }));
}

/** Switches the shell ("terminal" <-> "gui") and saves it like any other setting. */
export function setMode(mode: Mode): void {
  updateSettings((s) => ({ ...s, mode }));
}

export function toggleMode(): void {
  setMode(settingsStore.get().mode === "gui" ? "terminal" : "gui");
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

/**
 * Another tab wrote the mirror (the browser's `storage` event only fires in the OTHER tabs). Take its settings, time and dirty flag
 * as they are. No echo: nothing is written back to localStorage (the value is already there, and a write would fire the event in
 * the other tab again) and no server push is scheduled (the tab that made the edit pushes it).
 */
export function adoptFromOtherTab(raw: string | null): void {
  const other = parseMirror(raw);
  if (!other || sameMirror(mirror, other)) return;
  mirror.settings = other.settings;
  mirror.updatedAt = other.updatedAt;
  mirror.dirty = other.dirty;
  settingsStore.set(() => normalize(other.settings).settings);
}

/** The backend stored our copy. Edits made while the request was in flight stay dirty. */
export function markSynced(sent: string, updatedAt: number): void {
  if (JSON.stringify(mirror.settings) !== sent) return;
  mirror.updatedAt = updatedAt;
  mirror.dirty = false;
  persist();
}
