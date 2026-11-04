/**
 * Settings schema (pure; unit-tested). Mirrors backend/openterm/settings_store.py: every field optional on
 * the wire, defaults filled in here. Invalid fields from storage fall back to their default (with a note in
 * `errors`) so a bad value never blocks cold start.
 */
import { isTheme, type ThemeName } from "./themes";

export const SETTINGS_VERSION = 1;
export const CHART_RANGES = ["1D", "5D", "1M", "3M", "6M", "YTD", "1Y", "2Y", "5Y", "10Y", "MAX"] as const;
export const CHART_TYPES = ["CANDLE", "HOLLOW", "OHLC", "LINE", "AREA", "BASELINE", "HEIKIN"] as const;
export const THOUSANDS = [",", ".", " ", "'", ""] as const;
export const DECIMALS = [".", ","] as const;
/** Seconds, [min, max]. The floors keep the free providers inside their rate limits. */
export const POLL_BOUNDS = { news: [30, 600], movers: [30, 600], crypto: [15, 600], sources: [5, 120] } as const;
export type PollKey = keyof typeof POLL_BOUNDS;
export const MAX_CLOCKS = 3;
export const AI_PROVIDERS = [
  "openrouter", "openai", "anthropic", "opencodego", "deepseek", "groq", "mistral", "xai", "together", "fireworks", "gemini", "ollama",
] as const;
/** Models the AI rows cycle through (any other id works via `SETTINGS AI MODEL <id>`). */
export const AI_MODEL_CHOICES = ["deepseek/deepseek-v4-pro", "deepseek/deepseek-v4.1-flash", "anthropic/claude-sonnet-5.5", "anthropic/claude-haiku-5.5", "google/gemma-4-31b-it:free"] as const;
export const AI_VISION_CHOICES = ["deepseek/deepseek-v4.1-flash", "anthropic/claude-haiku-5.5", "anthropic/claude-sonnet-5.5", "google/gemma-4-31b-it:free"] as const;
export const AI_MODEL_RE = /^[A-Za-z0-9._:/-]{1,80}$/;
/** GUI mode: which shell wraps the workspace. "terminal" is the keyboard-first look, "gui" adds a menu bar and sidebar. */
export const MODES = ["terminal", "gui"] as const;
export type Mode = (typeof MODES)[number];

export interface Settings {
  /**
   * Which shell is shown. Defaults to "gui" for a brand-new user (nothing saved anywhere), but a SAVED settings
   * object with no `mode` field means "terminal": everyone who saved settings before GUI mode existed keeps the
   * terminal they chose. See `normalize` and `diffFromDefaults`.
   */
  mode: Mode;
  theme: ThemeName;
  vim: boolean;
  numberFormat: { thousands: (typeof THOUSANDS)[number]; decimal: (typeof DECIMALS)[number] };
  /** "LOCAL", "UTC" or an IANA zone such as "America/New_York". */
  clocks: string[];
  chart: { range: (typeof CHART_RANGES)[number]; type: (typeof CHART_TYPES)[number] };
  poll: Record<PollKey, number>;
  /** Keybinding overrides: action -> chords (replaces that action's defaults). */
  keys: Record<string, string[]>;
  /** Phase 16: which model the AI panels call (OpenRouter by default; the key lives in APIKEYS, never here). */
  ai: { model: string; visionModel: string; provider: (typeof AI_PROVIDERS)[number] };
}

export const DEFAULTS: Settings = Object.freeze({
  mode: "gui",
  theme: "amber",
  vim: false,
  numberFormat: { thousands: ",", decimal: "." },
  clocks: ["LOCAL", "UTC"],
  chart: { range: "1Y", type: "CANDLE" },
  poll: { news: 60, movers: 60, crypto: 30, sources: 10 },
  keys: {},
  ai: { model: "deepseek/deepseek-v4-pro", visionModel: "deepseek/deepseek-v4.1-flash", provider: "openrouter" },
}) as Settings;

const ZONE_RE = /^(LOCAL|UTC|[A-Za-z]+(?:\/[A-Za-z0-9_+-]+){1,2})$/;
const ACTION_RE = /^[A-Za-z][A-Za-z0-9]{0,39}$/;

/** LOCAL, UTC or a zone this browser's Intl knows. */
export function isZone(z: unknown): z is string {
  if (typeof z !== "string" || !ZONE_RE.test(z)) return false;
  if (z === "LOCAL" || z === "UTC") return true;
  try {
    new Intl.DateTimeFormat("en-GB", { timeZone: z });
    return true;
  } catch {
    return false;
  }
}

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const oneOf = <T extends readonly unknown[]>(list: T, v: unknown): v is T[number] => list.includes(v);

/** Fills defaults and drops invalid fields. Never throws. */
export function normalize(raw: unknown): { settings: Settings; errors: string[] } {
  const errors: string[] = [];
  const d = DEFAULTS;
  const r = isObj(raw) ? raw : {};
  if (raw != null && !isObj(raw)) errors.push("settings is not an object");
  // The mode rule (three cases):
  //   nothing saved at all (raw is null/undefined)  -> the default, "gui" (a brand-new user)
  //   a saved object WITHOUT a `mode` field          -> "terminal" (saved before GUI mode existed)
  //   a saved object with a bad `mode` value         -> "terminal" plus an error note (never block start-up)
  const mode: Mode = raw == null || !isObj(raw) ? d.mode : oneOf(MODES, r.mode) ? r.mode : "terminal";
  if (isObj(raw) && r.mode !== undefined && !oneOf(MODES, r.mode)) errors.push("mode");
  const pick = <T>(key: string, ok: boolean, value: T, fallback: T): T => {
    if (r[key] === undefined) return fallback;
    if (ok) return value;
    errors.push(key);
    return fallback;
  };

  const nf = isObj(r.numberFormat) ? r.numberFormat : {};
  let numberFormat = {
    thousands: oneOf(THOUSANDS, nf.thousands) ? nf.thousands : d.numberFormat.thousands,
    decimal: oneOf(DECIMALS, nf.decimal) ? nf.decimal : d.numberFormat.decimal,
  };
  if (numberFormat.thousands === numberFormat.decimal) {
    errors.push("numberFormat");
    numberFormat = { ...d.numberFormat };
  }

  const ch = isObj(r.chart) ? r.chart : {};
  const chart = {
    range: oneOf(CHART_RANGES, ch.range) ? ch.range : d.chart.range,
    type: oneOf(CHART_TYPES, ch.type) ? ch.type : d.chart.type,
  };

  const pr = isObj(r.poll) ? r.poll : {};
  const poll = { ...d.poll };
  for (const k of Object.keys(POLL_BOUNDS) as PollKey[]) {
    const v = pr[k];
    if (v === undefined) continue;
    const [lo, hi] = POLL_BOUNDS[k];
    if (typeof v === "number" && Number.isInteger(v) && v >= lo && v <= hi) poll[k] = v;
    else errors.push(`poll.${k}`);
  }

  const clocksOk = Array.isArray(r.clocks) && r.clocks.length >= 1 && r.clocks.length <= MAX_CLOCKS && r.clocks.every(isZone);
  const keys: Record<string, string[]> = {};
  if (isObj(r.keys)) {
    for (const [a, c] of Object.entries(r.keys)) {
      if (ACTION_RE.test(a) && Array.isArray(c) && c.length <= 4 && c.every((x) => typeof x === "string" && x.length > 0 && x.length <= 32)) {
        keys[a] = [...new Set(c as string[])];
      } else errors.push(`keys.${a}`);
    }
  } else if (r.keys !== undefined) errors.push("keys");

  const ai = isObj(r.ai) ? r.ai : {};
  const aiOut = { ...d.ai };
  for (const k of ["model", "visionModel"] as const) {
    if (ai[k] === undefined) continue;
    if (typeof ai[k] === "string" && AI_MODEL_RE.test(ai[k] as string)) aiOut[k] = ai[k] as string;
    else errors.push(`ai.${k}`);
  }
  if (ai.provider !== undefined) {
    if (oneOf(AI_PROVIDERS, ai.provider)) aiOut.provider = ai.provider;
    else errors.push("ai.provider");
  }
  if (r.ai !== undefined && !isObj(r.ai)) errors.push("ai");

  return {
    settings: {
      mode,
      theme: pick("theme", isTheme(r.theme), r.theme as ThemeName, d.theme),
      vim: pick("vim", typeof r.vim === "boolean", r.vim as boolean, d.vim),
      numberFormat,
      clocks: pick("clocks", clocksOk, (r.clocks as string[])?.slice(), [...d.clocks]),
      chart,
      poll,
      keys,
      ai: aiOut,
    },
    errors,
  };
}

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

/**
 * What the backend stores: only the fields that differ from the defaults.
 * `mode` is the exception: its stored form is compared with the LEGACY default ("terminal", what a saved object
 * without `mode` means), so "gui" is always written out and "terminal" is left out. That keeps every saved
 * terminal-mode document byte-identical to what it was before GUI mode existed.
 */
export function diffFromDefaults(s: Settings): Partial<Settings> {
  const out: Partial<Settings> = {};
  for (const k of Object.keys(DEFAULTS) as (keyof Settings)[]) {
    if (k === "mode") {
      if (s.mode === "gui") out.mode = "gui";
    } else if (k === "keys") {
      if (Object.keys(s.keys).length) out.keys = s.keys;
    } else if (!same(s[k], DEFAULTS[k])) (out as Record<string, unknown>)[k] = s[k];
  }
  return out;
}

/** Steps through a list (wrapping), for keyboard editing with h/l or arrow keys. */
export function cycle<T>(list: readonly T[], current: T, dir: 1 | -1): T {
  const i = list.indexOf(current);
  return list[(((i < 0 ? 0 : i) + dir) % list.length + list.length) % list.length];
}

/** Steps a poll interval inside its bounds (5 s steps under a minute, then 30 s). */
export function stepPoll(key: PollKey, value: number, dir: 1 | -1): number {
  const [lo, hi] = POLL_BOUNDS[key];
  const step = value + dir * (dir > 0 ? (value >= 60 ? 30 : 5) : value > 60 ? 30 : 5);
  return Math.min(hi, Math.max(lo, step));
}

/** Reconcile the localStorage mirror with the backend copy at startup. */
export function reconcile(
  local: { updatedAt: number; dirty: boolean },
  remote: { settings: unknown; updated_at: number | null },
): "push" | "adopt" | "keep" {
  if (remote.settings == null) return local.dirty || local.updatedAt > 0 ? "push" : "keep";
  const rAt = remote.updated_at ?? 0;
  if (local.dirty && local.updatedAt > rAt) return "push";
  return rAt === local.updatedAt && !local.dirty ? "keep" : "adopt";
}
