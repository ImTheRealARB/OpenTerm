/**
 * The settings mirror: what is kept in localStorage under `openterm.settings`. Pure (no browser APIs), so it is
 * unit-tested. runtime.ts owns the live copy; this file only knows the shape and how to read another tab's copy.
 */
import type { FieldTimes, Settings } from "./schema";

export interface Mirror {
  settings: Partial<Settings>;
  /** Backend `updated_at` of the copy we hold, or local time of an unsynced edit (epoch seconds). */
  updatedAt: number;
  /** Changed locally and not yet stored by the backend. */
  dirty: boolean;
  /**
   * When each top-level field last changed (epoch seconds; see `FieldTimes` in schema.ts). Missing in a mirror saved before
   * per-field sync existed: schema.ts `effectiveTimes` then treats every field as changed at `updatedAt`.
   */
  fieldTimes?: FieldTimes;
}

/**
 * Reads the text another tab just wrote to localStorage (the `storage` event's `newValue`).
 * Returns null for a removed key, text that is not JSON, or JSON that is not a mirror object:
 * a broken value from another tab must never replace this tab's settings.
 */
export function parseMirror(raw: string | null): Mirror | null {
  if (!raw) return null;
  let v: unknown;
  try {
    v = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!v || typeof v !== "object" || Array.isArray(v)) return null;
  const m = v as Partial<Mirror>;
  if (!m.settings || typeof m.settings !== "object" || Array.isArray(m.settings)) return null;
  return { settings: m.settings, updatedAt: typeof m.updatedAt === "number" ? m.updatedAt : 0, dirty: m.dirty === true, fieldTimes: parseFieldTimes(m.fieldTimes) };
}

/** A stored `fieldTimes`: an object of finite non-negative numbers, or undefined (absent or malformed = a legacy mirror). */
export function parseFieldTimes(v: unknown): FieldTimes | undefined {
  if (!v || typeof v !== "object" || Array.isArray(v)) return undefined;
  const out: FieldTimes = {};
  for (const [k, t] of Object.entries(v)) {
    if (typeof t === "number" && Number.isFinite(t) && t >= 0) out[k] = t;
  }
  return out;
}

/** Same settings, times and dirty flag? Then there is nothing to adopt. */
export function sameMirror(a: Mirror, b: Mirror): boolean {
  return (
    a.updatedAt === b.updatedAt &&
    a.dirty === b.dirty &&
    JSON.stringify(a.settings) === JSON.stringify(b.settings) &&
    JSON.stringify(a.fieldTimes) === JSON.stringify(b.fieldTimes)
  );
}
