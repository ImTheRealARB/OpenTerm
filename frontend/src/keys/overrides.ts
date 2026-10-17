/**
 * Keybinding overrides (pure; unit-tested). The defaults live in keybindings.json; the user's overrides
 * (SETTINGS, persisted with the other settings) replace an action's chord list. Chords use the
 * canonical form produced by `chord()` in keys.ts, e.g. "Ctrl+Shift+ArrowLeft", "Alt+W", "?".
 */
export type Bindings = Record<string, string[]>;
export interface Hit {
  action: string;
  n?: number;
}

/** Not rebindable: Escape drives every overlay / vim mode, focusPanel is the Alt+1..9 range. */
export const FIXED_ACTIONS: ReadonlySet<string> = new Set(["escape", "focusPanel"]);

/** Chords the browser keeps for itself (the page never sees them, or cannot cancel them). */
export const BROWSER_RESERVED: ReadonlySet<string> = new Set([
  "Ctrl+W", "Ctrl+T", "Ctrl+N", "Ctrl+Shift+W", "Ctrl+Shift+T", "Ctrl+Shift+N", "Ctrl+Tab", "Ctrl+Shift+Tab",
  "Ctrl+Q", "Alt+F4", "F11", "Ctrl+PageUp", "Ctrl+PageDown",
  ...Array.from({ length: 9 }, (_, i) => `Ctrl+${i + 1}`),
]);

/** Used by vim mode in grids and lists (half-page down / up) while vim mode is on. */
export const VIM_CHORDS: ReadonlySet<string> = new Set(["Ctrl+D", "Ctrl+U"]);

/** Keys that panels and the command line need unmodified (typing, navigation). */
const PLAIN_NAMED = new Set([
  "Enter", "Backspace", "Delete", "Tab", "Shift+Tab", " ", "Space", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight",
  "Home", "End", "PageUp", "PageDown", "Escape",
]);

/** Expands the "Mod+1..9" range form into its nine chords. */
export function expand(chord: string): { chord: string; n?: number }[] {
  const range = /^(.*)\+1\.\.9$/.exec(chord);
  if (!range) return [{ chord }];
  return Array.from({ length: 9 }, (_, i) => ({ chord: `${range[1]}+${i + 1}`, n: i + 1 }));
}

/** Defaults with the overrides applied. Unknown actions and fixed actions in `overrides` are ignored. */
export function mergeBindings(defaults: Bindings, overrides: Bindings | undefined): Bindings {
  const out: Bindings = {};
  for (const [action, chords] of Object.entries(defaults)) {
    const o = overrides?.[action];
    out[action] = o && !FIXED_ACTIONS.has(action) ? [...new Set(o)] : [...chords];
  }
  return out;
}

/** chord -> action lookup. On a duplicate (only possible with hand-edited data) the first action wins. */
export function buildIndex(bindings: Bindings): Map<string, Hit> {
  const index = new Map<string, Hit>();
  for (const [action, chords] of Object.entries(bindings)) {
    for (const c of chords) for (const e of expand(c)) if (!index.has(e.chord)) index.set(e.chord, { action, n: e.n });
  }
  return index;
}

export type ChordCheck = { ok: true } | { ok: false; reason: string; conflict?: string };

/** Why `chord` cannot be bound to `action` given the current effective bindings, if it cannot. */
export function checkChord(bindings: Bindings, action: string, chord: string, opts: { vim?: boolean } = {}): ChordCheck {
  if (!(action in bindings)) return { ok: false, reason: `UNKNOWN ACTION ${action}` };
  if (FIXED_ACTIONS.has(action)) return { ok: false, reason: "THIS SHORTCUT IS FIXED" };
  if (!chord) return { ok: false, reason: "EMPTY CHORD" };
  if (/^(Ctrl|Alt|Shift|Meta)$/.test(chord.split("+").pop()!)) return { ok: false, reason: "PRESS A KEY WITH THE MODIFIER" };
  if (BROWSER_RESERVED.has(chord)) return { ok: false, reason: `${chord} IS RESERVED BY THE BROWSER` };
  if (opts.vim && VIM_CHORDS.has(chord)) return { ok: false, reason: `${chord} IS USED BY VIM MODE` };
  const parts = chord.split("+");
  const key = parts[parts.length - 1] || "+";
  const mods = parts.slice(0, -1);
  const hasCtrlAlt = mods.includes("Ctrl") || mods.includes("Alt");
  if (!hasCtrlAlt && (/^[A-Z0-9]$/.test(key) || PLAIN_NAMED.has(chord))) {
    return { ok: false, reason: `${chord} TYPES OR NAVIGATES: ADD CTRL OR ALT` };
  }
  const hit = buildIndex(bindings).get(chord);
  if (hit && hit.action === action) return { ok: false, reason: `${chord} IS ALREADY BOUND TO THIS ACTION` };
  if (hit) return { ok: false, reason: `${chord} IS USED BY ${hit.action}`, conflict: hit.action };
  return { ok: true };
}

/** The overrides to persist: only actions whose chord list differs from the default. */
export function diffBindings(defaults: Bindings, effective: Bindings): Bindings {
  const out: Bindings = {};
  for (const [action, chords] of Object.entries(effective)) {
    const d = defaults[action];
    if (!d || FIXED_ACTIONS.has(action)) continue;
    if (d.length !== chords.length || d.some((c, i) => c !== chords[i])) out[action] = [...chords];
  }
  return out;
}
