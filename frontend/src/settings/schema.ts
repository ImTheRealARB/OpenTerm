/**
 * Settings schema (pure; unit-tested). Mirrors backend/openterm/settings_store.py: every field optional on
 * the wire, defaults filled in here. Invalid fields from storage fall back to their default (with a note in
 * `errors`) so a bad value never blocks cold start.
 */
import { CHART_TYPES, type ChartType } from "../chart/chartTypes";
import { CHART_RANGES } from "../chart/gpRanges";
import { isFontName } from "./font";
import { isTheme, type ThemeName } from "./themes";

// The chart ranges and types are defined once (chart/gpRanges.ts, chart/chartTypes.ts; both are tiny and import
// nothing) and re-exported here so settings code keeps importing them from the schema.
export { CHART_RANGES, CHART_TYPES };
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
/** Search providers for the AI's opt-in web access (SETTINGS AI WEB); keys live in APIKEYS. Keep equal to settings_store.AI_WEB_PROVIDERS. */
export const AI_WEB_PROVIDERS = ["brave", "tavily", "searxng"] as const;
export const AI_MODEL_CHOICES = ["deepseek/deepseek-v4-pro", "deepseek/deepseek-v4.1-flash", "anthropic/claude-sonnet-5.5", "anthropic/claude-haiku-5.5", "google/gemma-4-31b-it:free"] as const;
export const AI_VISION_CHOICES = ["deepseek/deepseek-v4.1-flash", "anthropic/claude-haiku-5.5", "anthropic/claude-sonnet-5.5", "google/gemma-4-31b-it:free"] as const;
export const AI_MODEL_RE = /^[A-Za-z0-9._:/-]{1,80}$/;
/** GUI mode: which shell wraps the workspace. "terminal" is the keyboard-first look, "gui" adds a menu bar and sidebar. */
export const MODES = ["terminal", "gui"] as const;
export type Mode = (typeof MODES)[number];

/** What a fresh session opens: the HOME page, or the layout that was open last time (see home/startup.ts). */
export const STARTUPS = ["home", "layout"] as const;
export type Startup = (typeof STARTUPS)[number];
/** Row-number gutter on the quote grids (1) 2) 3) ...). "auto" = on in Terminal, off in GUI; one field cannot have a mode-dependent default, so the default is the word "auto". */
export const ROW_NUMBERS = ["auto", "on", "off"] as const;
export type RowNumbers = (typeof ROW_NUMBERS)[number];
/** The ticker tape (HOME and the optional global bar). At most this many symbols; each must look like a Yahoo-style symbol. */
export const TAPE_MAX = 30;
export const TAPE_SYMBOL_RE = /^[A-Z0-9^][A-Z0-9.\-=^&]{0,19}$/;
/** Default tape: global indices, Indian indices, commodities + FX, crypto, rates + volatility (spellings as in boards.ts). */
export const TAPE_DEFAULT: readonly string[] = [
  "^GSPC", "^IXIC", "^DJI", "^FTSE", "^GDAXI", "^N225", "^HSI", "^NSEI", "^NSEBANK", "^BSESN",
  "GC=F", "BZ=F", "CL=F", "NG=F", "HG=F", "USDINR=X", "EURUSD=X", "DX-Y.NYB", "BTC-USD", "ETH-USD", "^TNX", "^VIX",
];

export interface Settings {
  /**
   * Which shell is shown. Defaults to "gui" for a brand-new user (nothing saved anywhere), but a SAVED settings
   * object with no `mode` field means "terminal": everyone who saved settings before GUI mode existed keeps the
   * terminal they chose. See `normalize` and `diffFromDefaults`.
   */
  mode: Mode;
  theme: ThemeName;
  /** Name of an installed font for the whole app ("" = the built-in font). See settings/font.ts. */
  font: string;
  vim: boolean;
  numberFormat: { thousands: (typeof THOUSANDS)[number]; decimal: (typeof DECIMALS)[number] };
  /** "LOCAL", "UTC" or an IANA zone such as "America/New_York". */
  clocks: string[];
  chart: { range: (typeof CHART_RANGES)[number]; type: ChartType };
  poll: Record<PollKey, number>;
  /** Keybinding overrides: action -> chords (replaces that action's defaults). */
  keys: Record<string, string[]>;
  /** Phase 16: which model the AI panels call (OpenRouter by default; the key lives in APIKEYS, never here). */
  ai: { model: string; visionModel: string; provider: (typeof AI_PROVIDERS)[number]; /** Keep the redacted question and answer of each AI run next to the audit ledger (local only; off by default). */ storeText: boolean; web: boolean; webProvider: (typeof AI_WEB_PROVIDERS)[number] };
  /** "home" = a new session opens the HOME page; "layout" = it restores the saved workspace as before. */
  startup: Startup;
  /** Row-number gutter on Q, WL, WEI, FX and CMDTY (type a number, Enter): auto = Terminal on, GUI off. */
  rowNumbers: RowNumbers;
  /** Also show the ticker tape in the global top bar on every screen (HOME always has its own). */
  tape: boolean;
  /** Symbols on the tape, in order (TAPE ADD / TAPE DEL / TAPE RESET). */
  tapeSymbols: string[];
  /** Preferred source per kind of data, tried first (SETTINGS SOURCE HISTORY NASDAQ): capability -> source name. The default order still backs it up. */
  sources: Record<string, string>;
  /** Phase 22: inside a link group, which chart views follow each other (SETTINGS LINK CROSSHAIR|RANGE|INTERVAL ON|OFF). */
  link: { crosshair: boolean; range: boolean; interval: boolean };
}

export const DEFAULTS: Settings = Object.freeze({
  mode: "gui",
  theme: "amber",
  font: "",
  vim: false,
  numberFormat: { thousands: ",", decimal: "." },
  clocks: ["LOCAL", "UTC"],
  chart: { range: "1Y", type: "CANDLE" },
  poll: { news: 60, movers: 60, crypto: 30, sources: 10 },
  keys: {},
  ai: { model: "deepseek/deepseek-v4-pro", visionModel: "deepseek/deepseek-v4.1-flash", provider: "openrouter", storeText: false, web: false, webProvider: "brave" },
  startup: "home",
  rowNumbers: "auto",
  tape: false,
  tapeSymbols: [...TAPE_DEFAULT],
  sources: {},
  link: { crosshair: true, range: true, interval: true },
}) as Settings;

export const SOURCE_NAME_RE = /^[a-z][a-z0-9_]{0,39}$/;

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
  if (ai.storeText !== undefined) {
    if (typeof ai.storeText === "boolean") aiOut.storeText = ai.storeText;
    else errors.push("ai.storeText");
  }
  if (ai.web !== undefined) {
    if (typeof ai.web === "boolean") aiOut.web = ai.web;
    else errors.push("ai.web");
  }
  if (ai.webProvider !== undefined) {
    if (oneOf(AI_WEB_PROVIDERS, ai.webProvider)) aiOut.webProvider = ai.webProvider;
    else errors.push("ai.webProvider");
  }
  if (r.ai !== undefined && !isObj(r.ai)) errors.push("ai");

  // tapeSymbols: a list of at most TAPE_MAX distinct, well-formed symbols (empty is allowed: an empty tape).
  const tapeOk =
    Array.isArray(r.tapeSymbols) && r.tapeSymbols.length <= TAPE_MAX && new Set(r.tapeSymbols).size === r.tapeSymbols.length &&
    r.tapeSymbols.every((x) => typeof x === "string" && TAPE_SYMBOL_RE.test(x));

  // sources: capability -> source name. The backend checks the capability against its own table (unknown ones are refused there).
  const sourcesOut: Record<string, string> = {};
  if (isObj(r.sources)) {
    for (const [cap, name] of Object.entries(r.sources)) {
      if (/^[a-z][a-z0-9_]{0,39}$/.test(cap) && typeof name === "string" && SOURCE_NAME_RE.test(name)) sourcesOut[cap] = name;
      else errors.push(`sources.${cap}`);
    }
  } else if (r.sources !== undefined) errors.push("sources");

  // link: three on/off switches for chart sync inside a link group; a bad or missing switch keeps its default.
  const lk = isObj(r.link) ? r.link : {};
  const link = { ...d.link };
  for (const k of ["crosshair", "range", "interval"] as const) {
    if (lk[k] === undefined) continue;
    if (typeof lk[k] === "boolean") link[k] = lk[k] as boolean;
    else errors.push(`link.${k}`);
  }
  if (r.link !== undefined && !isObj(r.link)) errors.push("link");

  return {
    settings: {
      mode,
      theme: pick("theme", isTheme(r.theme), r.theme as ThemeName, d.theme),
      font: pick("font", isFontName(r.font), r.font as string, d.font),
      vim: pick("vim", typeof r.vim === "boolean", r.vim as boolean, d.vim),
      numberFormat,
      clocks: pick("clocks", clocksOk, (r.clocks as string[])?.slice(), [...d.clocks]),
      chart,
      poll,
      keys,
      ai: aiOut,
      startup: pick("startup", oneOf(STARTUPS, r.startup), r.startup as Startup, d.startup),
      rowNumbers: pick("rowNumbers", oneOf(ROW_NUMBERS, r.rowNumbers), r.rowNumbers as RowNumbers, d.rowNumbers),
      tape: pick("tape", typeof r.tape === "boolean", r.tape as boolean, d.tape),
      tapeSymbols: pick("tapeSymbols", tapeOk, (r.tapeSymbols as string[])?.slice(), [...d.tapeSymbols]),
      sources: sourcesOut,
      link,
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
    } else if (k === "sources") {
      if (Object.keys(s.sources).length) out.sources = s.sources;
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

// --- Per-field sync ---------------------------------------------------------------------------
// Two devices editing DIFFERENT settings must both keep their edit, so every top-level field carries its own last-change
// time instead of the whole document having one. The backend (settings_store.py) merges the same way; keep the two in step.
// A time also covers "reset to default": the field is absent from the stored settings but has a time (a tombstone), so a
// reset on one device is not undone by an older copy on another. A time of 0 means "never set" and never beats anything.

/** Epoch seconds of the last change of each top-level settings field. */
export type FieldTimes = Record<string, number>;
/** The top-level fields that sync independently (the same list the backend accepts). */
export const SETTING_FIELDS = Object.keys(DEFAULTS) as (keyof Settings)[];

const goodTime = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v) && v >= 0;

/**
 * The change time of every field. `fieldTimes` undefined = a copy saved before per-field times existed (an old localStorage
 * mirror, an old server document): every field, even one left out because it was at its default, counts as changed when
 * that whole copy was saved (`docTime`), which is exactly what whole-document last-write-wins meant. A copy that has
 * `fieldTimes` does NOT fall back to `docTime`: a field it has no time for was never set.
 */
export function effectiveTimes(fieldTimes: FieldTimes | undefined, docTime: number): FieldTimes {
  const out: FieldTimes = {};
  for (const f of SETTING_FIELDS) out[f] = fieldTimes ? (goodTime(fieldTimes[f]) ? fieldTimes[f] : 0) : goodTime(docTime) ? docTime : 0;
  return out;
}

/** Times after a local edit: every field whose stored form changed (value, added or removed) gets `now`; the rest keep theirs. */
export function stampChanges(before: Record<string, unknown>, after: Record<string, unknown>, times: FieldTimes, now: number): FieldTimes {
  const out = { ...times };
  for (const f of SETTING_FIELDS) if (!same(before[f], after[f])) out[f] = now;
  return out;
}

/** A settings copy in stored form (fields at their default are left out) with its field times (see `effectiveTimes`). */
export interface FieldDoc {
  settings: Record<string, unknown>;
  times: FieldTimes;
}
export interface MergeResult {
  settings: Record<string, unknown>;
  times: FieldTimes;
  /** The local copy changed a field later than the remote one: the remote copy has to be sent ours. */
  push: boolean;
  /** At least one field took the remote value, so the running settings must be re-applied. */
  changed: boolean;
}

/**
 * Per field, the later change wins. Remote wins a tie, but only when it was ever set: two zeros mean nobody set the field,
 * and then the local value stays (a default, or a seed) and nothing is sent for it.
 */
export function mergeFields(local: FieldDoc, remote: FieldDoc): MergeResult {
  const settings: Record<string, unknown> = {};
  const times: FieldTimes = {};
  let push = false;
  let changed = false;
  for (const f of SETTING_FIELDS) {
    const lt = local.times[f] ?? 0;
    const rt = remote.times[f] ?? 0;
    const takeRemote = rt > 0 && rt >= lt;
    const from = takeRemote ? remote : local;
    if (f in from.settings) settings[f] = from.settings[f]; // absent on the winning side = reset to default
    times[f] = takeRemote ? rt : lt;
    if (lt > rt) push = true;
    if (takeRemote && !same(local.settings[f], remote.settings[f])) changed = true;
  }
  return { settings, times, push, changed };
}

/**
 * Reconcile the localStorage mirror with the backend copy (at startup, and with the answer to every PUT).
 * `remote.settings` null = the backend has nothing saved yet: all its times are 0, so anything we ever set is pushed.
 * `remote.field_times` missing (an old server) = the legacy rule of `effectiveTimes`.
 */
export function reconcile(
  local: { settings: Record<string, unknown>; updatedAt: number; fieldTimes?: FieldTimes },
  remote: { settings: Record<string, unknown> | null; updated_at: number | null; field_times?: FieldTimes },
): MergeResult {
  const localDoc: FieldDoc = { settings: local.settings, times: effectiveTimes(local.fieldTimes, local.updatedAt) };
  const remoteDoc: FieldDoc =
    remote.settings == null
      ? { settings: {}, times: effectiveTimes({}, 0) }
      : { settings: remote.settings, times: effectiveTimes(remote.field_times, remote.updated_at ?? 0) };
  return mergeFields(localDoc, remoteDoc);
}
