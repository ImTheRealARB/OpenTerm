/**
 * Command-line settings (pure; unit-tested):
 *   THEME [AMBER|GREEN|WHITE|LIGHT]
 *   SETTINGS MODE GUI|TERMINAL | THEME name | FONT name|DEFAULT | VIM ON|OFF | CLOCKS zone... | CHART [range] [type] | THOUSANDS COMMA|DOT|SPACE|APOS|NONE
 *            | DECIMAL DOT|COMMA | POLL NEWS|MOVERS|CRYPTO|SOURCES seconds | AI MODEL|VISION|PROVIDER ... | KEYS RESET | RESET
 */
import {
  AI_MODEL_RE, AI_PROVIDERS, CHART_RANGES, CHART_TYPES, DEFAULTS, MAX_CLOCKS, POLL_BOUNDS, isZone, type PollKey, type Settings,
} from "./schema";
import { FONT_NAME_RE } from "./font";
import { FONT_PRESETS, cyclePreset, findPreset, type FontPreset } from "./fontPresets";
import { THEMES, isTheme } from "./themes";

export type SettingsCommand = { ok: true; next: Settings; message: string } | { ok: false; error: string };

const SEPARATORS: Record<string, string> = { COMMA: ",", DOT: ".", SPACE: " ", APOS: "'", NONE: "" };
const SEP_NAMES: Record<string, string> = { ",": "COMMA", ".": "DOT", " ": "SPACE", "'": "APOS", "": "NONE" };

const fail = (error: string): SettingsCommand => ({ ok: false, error });

export function themeArgs(args: string[], cur: Settings): SettingsCommand | null {
  if (!args.length) return null; // bare THEME opens SETTINGS
  const name = args[0].toLowerCase();
  if (!isTheme(name)) return fail(`THEME: ${THEMES.join(" ").toUpperCase()}`);
  return { ok: true, next: { ...cur, theme: name }, message: `THEME ${name.toUpperCase()}` };
}

export function settingsArgs(args: string[], cur: Settings): SettingsCommand | null {
  if (!args.length) return null;
  const [rawKey, ...rest] = args;
  const key = rawKey.toUpperCase();
  const word = (rest[0] ?? "").toUpperCase();
  switch (key) {
    case "THEME":
      return themeArgs(rest, cur) ?? fail(`SETTINGS THEME ${THEMES.join("|").toUpperCase()}`);
    case "MODE":
      if (word !== "GUI" && word !== "TERMINAL") return fail("SETTINGS MODE GUI|TERMINAL");
      return { ok: true, next: { ...cur, mode: word.toLowerCase() as Settings["mode"] }, message: `MODE ${word}` };
    case "FONT": {
      const usage = `SETTINGS FONT NEXT | PREV | <PRESET> | <ANY INSTALLED FONT>. PRESETS: ${FONT_PRESETS.map((p) => (p.name || "DEFAULT").toUpperCase()).join(", ")}`;
      const name = rest.join(" ").trim();
      if (!name) return fail(usage);
      const pick = (p: FontPreset): SettingsCommand => ({
        ok: true, next: { ...cur, font: p.name }, message: `FONT ${p.label.toUpperCase()}`,
      });
      const up = name.toUpperCase();
      if (up === "NEXT" || up === "PREV") return pick(cyclePreset(cur.font, up === "NEXT" ? 1 : -1));
      const preset = findPreset(name);
      if (preset) return pick(preset);
      if (!FONT_NAME_RE.test(name)) return fail(`FONT NAME: LETTERS, DIGITS, SPACES AND . _ + - ONLY (60 MAX). ${usage}`);
      return { ok: true, next: { ...cur, font: name }, message: `FONT ${name}` }; // any other installed font
    }
    case "VIM":
      if (word !== "ON" && word !== "OFF") return fail("SETTINGS VIM ON|OFF");
      return { ok: true, next: { ...cur, vim: word === "ON" }, message: `VIM MODE ${word}` };
    case "CLOCK":
    case "CLOCKS": {
      if (!rest.length || rest.length > MAX_CLOCKS) return fail(`SETTINGS CLOCKS: 1-${MAX_CLOCKS} ZONES (LOCAL, UTC, AREA/CITY)`);
      const zones = rest.map((z) => (/^(local|utc)$/i.test(z) ? z.toUpperCase() : z));
      const bad = zones.find((z) => !isZone(z));
      if (bad) return fail(`UNKNOWN TIME ZONE ${bad}`);
      // Canonical IANA spelling ("america/new_york" -> "America/New_York").
      const canon = zones.map((z) => (z === "LOCAL" || z === "UTC" ? z : new Intl.DateTimeFormat("en-GB", { timeZone: z }).resolvedOptions().timeZone));
      return { ok: true, next: { ...cur, clocks: canon }, message: `CLOCKS ${canon.join(" ").toUpperCase()}` };
    }
    case "CHART": {
      const chart = { ...cur.chart };
      for (const a of rest.map((x) => x.toUpperCase())) {
        if ((CHART_RANGES as readonly string[]).includes(a)) chart.range = a as Settings["chart"]["range"];
        else if ((CHART_TYPES as readonly string[]).includes(a)) chart.type = a as Settings["chart"]["type"];
        else return fail(`SETTINGS CHART [${CHART_RANGES.join("|")}] [${CHART_TYPES.join("|")}]`);
      }
      if (!rest.length) return fail("SETTINGS CHART range type, E.G. SETTINGS CHART 6M LINE");
      return { ok: true, next: { ...cur, chart }, message: `DEFAULT CHART ${chart.range} ${chart.type}` };
    }
    case "THOUSANDS":
    case "DECIMAL": {
      const sep = SEPARATORS[word];
      const allowed = key === "DECIMAL" ? ["DOT", "COMMA"] : Object.keys(SEPARATORS);
      if (sep === undefined || !allowed.includes(word)) return fail(`SETTINGS ${key} ${allowed.join("|")}`);
      const nf = { ...cur.numberFormat, [key === "DECIMAL" ? "decimal" : "thousands"]: sep } as Settings["numberFormat"];
      if (nf.thousands === nf.decimal) return fail("THOUSANDS SEPARATOR AND DECIMAL MARK MUST DIFFER");
      return { ok: true, next: { ...cur, numberFormat: nf }, message: `NUMBERS: THOUSANDS ${SEP_NAMES[nf.thousands]}, DECIMAL ${SEP_NAMES[nf.decimal]}` };
    }
    case "POLL": {
      const k = word.toLowerCase() as PollKey;
      if (!Object.hasOwn(POLL_BOUNDS, k)) return fail(`SETTINGS POLL ${Object.keys(POLL_BOUNDS).join("|").toUpperCase()} SECONDS`);
      const [lo, hi] = POLL_BOUNDS[k];
      const v = Number(rest[1]);
      if (!Number.isInteger(v) || v < lo || v > hi) return fail(`POLL ${word}: ${lo}-${hi} SECONDS`);
      return { ok: true, next: { ...cur, poll: { ...cur.poll, [k]: v } }, message: `POLL ${word} ${v}S (APPLIES WHEN THE PANEL REOPENS)` };
    }
    case "AI": {
      const usage = "SETTINGS AI MODEL <id> | VISION <id> | PROVIDER OPENROUTER|OPENAI|ANTHROPIC|OLLAMA | RESET";
      if (word === "RESET") return { ok: true, next: { ...cur, ai: { ...DEFAULTS.ai } }, message: "AI SETTINGS RESET TO DEFAULTS" };
      if (word === "PROVIDER") {
        const p = (rest[1] ?? "").toLowerCase();
        if (!(AI_PROVIDERS as readonly string[]).includes(p)) return fail(usage);
        return { ok: true, next: { ...cur, ai: { ...cur.ai, provider: p as Settings["ai"]["provider"] } }, message: `AI PROVIDER ${p.toUpperCase()}` };
      }
      if (word === "MODEL" || word === "VISION") {
        const id = rest[1] ?? "";
        if (!AI_MODEL_RE.test(id) || rest.length > 2) return fail(usage);
        const field = word === "MODEL" ? "model" : "visionModel";
        return { ok: true, next: { ...cur, ai: { ...cur.ai, [field]: id } }, message: `AI ${word} ${id}` };
      }
      return fail(usage);
    }
    case "KEYS":
      if (word !== "RESET") return fail("SETTINGS KEYS RESET (EDIT SHORTCUTS IN THE SETTINGS PANEL)");
      return { ok: true, next: { ...cur, keys: {} }, message: "SHORTCUTS RESET TO DEFAULTS" };
    case "RESET":
      // The shell (mode) is kept: RESET restores preferences, it must not switch between TERMINAL and GUI.
      return { ok: true, next: { ...DEFAULTS, mode: cur.mode, keys: {} }, message: "SETTINGS RESET TO DEFAULTS" };
    default:
      return fail("SETTINGS MODE|THEME|FONT|VIM|CLOCKS|CHART|THOUSANDS|DECIMAL|POLL|AI|KEYS|RESET ...");
  }
}
