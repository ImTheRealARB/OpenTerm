/**
 * Command-line settings (pure; unit-tested):
 *   THEME [AMBER|GREEN|WHITE|LIGHT]
 *   SETTINGS STARTUP HOME|LAYOUT | TAPE ON|OFF | MODE GUI|TERMINAL | THEME name | FONT name|DEFAULT | VIM ON|OFF | CLOCKS zone... | CHART [range] [type] | THOUSANDS COMMA|DOT|SPACE|APOS|NONE
 *            | SOURCE <capability> <source>|DEFAULT | SOURCE RESET | DECIMAL DOT|COMMA | POLL NEWS|MOVERS|CRYPTO|SOURCES seconds | AI MODEL|VISION|PROVIDER|STORETEXT ... | KEYS RESET | RESET
 */
import {
  AI_MODEL_RE, AI_PROVIDERS, AI_WEB_PROVIDERS, CHART_RANGES, CHART_TYPES, DEFAULTS, MAX_CLOCKS, POLL_BOUNDS, SOURCE_NAME_RE, isZone, type PollKey, type Settings,
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
    case "STARTUP":
      if (word !== "HOME" && word !== "LAYOUT") return fail("SETTINGS STARTUP HOME|LAYOUT (HOME = NEW SESSIONS OPEN THE HOME PAGE, LAYOUT = THEY RESTORE YOUR PANELS)");
      return { ok: true, next: { ...cur, startup: word.toLowerCase() as Settings["startup"] }, message: `STARTUP ${word}` };
    case "TAPE":
      if (word !== "ON" && word !== "OFF") return fail("SETTINGS TAPE ON|OFF (SHOW THE TICKER TAPE IN THE TOP BAR; TAPE ADD|DEL|RESET EDITS IT)");
      return { ok: true, next: { ...cur, tape: word === "ON" }, message: `TICKER TAPE IN THE TOP BAR ${word}` };
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
    case "SOURCE": {
      // SETTINGS SOURCE HISTORY NASDAQ: the source tried first for that kind of data; DEFAULT removes it, RESET removes all.
      const usage = "SETTINGS SOURCE <DATA> <SOURCE> | <DATA> DEFAULT | RESET, E.G. SETTINGS SOURCE HISTORY NASDAQ (DATA: HISTORY QUOTES PROFILE FUNDAMENTALS NEWS_SYMBOL ...; SOURCES LISTS THE NAMES)";
      if (word === "RESET") return { ok: true, next: { ...cur, sources: {} }, message: "SOURCE PREFERENCES CLEARED: THE DEFAULT ORDER APPLIES" };
      const cap = (rest[0] ?? "").toLowerCase() === "news" ? "news_symbol" : (rest[0] ?? "").toLowerCase();
      const name = (rest[1] ?? "").toLowerCase();
      if (!/^[a-z][a-z0-9_]{0,39}$/.test(cap) || !name || rest.length > 2) return fail(usage);
      const sources = { ...cur.sources };
      if (name === "default") {
        delete sources[cap];
        return { ok: true, next: { ...cur, sources }, message: `${cap.toUpperCase()} USES THE DEFAULT SOURCE ORDER` };
      }
      if (!SOURCE_NAME_RE.test(name)) return fail(usage);
      sources[cap] = name;
      return { ok: true, next: { ...cur, sources }, message: `${cap.toUpperCase()}: ${name.toUpperCase()} FIRST, THE DEFAULT ORDER BEHIND IT (SRC= PINS ONE COMMAND)` };
    }
    case "AI": {
      const usage = "SETTINGS AI MODEL <id> | VISION <id> | PROVIDER OPENROUTER|OPENAI|ANTHROPIC|OLLAMA | STORETEXT ON|OFF | WEB ON|OFF | WEB PROVIDER BRAVE|TAVILY|SEARXNG | RESET";
      if (word === "RESET") return { ok: true, next: { ...cur, ai: { ...DEFAULTS.ai } }, message: "AI SETTINGS RESET TO DEFAULTS" };
      if (word === "PROVIDER") {
        const p = (rest[1] ?? "").toLowerCase();
        if (!(AI_PROVIDERS as readonly string[]).includes(p)) return fail(usage);
        return { ok: true, next: { ...cur, ai: { ...cur.ai, provider: p as Settings["ai"]["provider"] } }, message: `AI PROVIDER ${p.toUpperCase()}` };
      }
      if (word === "STORETEXT") {
        const v = rest[1];
        if ((v !== "ON" && v !== "OFF") || rest.length > 2) return fail("SETTINGS AI STORETEXT ON|OFF (ON KEEPS THE REDACTED QUESTION AND ANSWER OF EACH AI RUN ON THIS MACHINE; PURGE IN AUDIT)");
        return { ok: true, next: { ...cur, ai: { ...cur.ai, storeText: v === "ON" } }, message: `AI STORETEXT ${v}${v === "ON" ? " (NEW RUNS KEEP THEIR REDACTED TEXT LOCALLY; PURGE IN AUDIT)" : " (NEW RUNS STORE NO TEXT; PURGE EXISTING TEXT IN AUDIT)"}` };
      }
      if (word === "WEB") {
        const w = (rest[1] ?? "").toUpperCase();
        if (w === "PROVIDER") {
          const p = (rest[2] ?? "").toLowerCase();
          if (!(AI_WEB_PROVIDERS as readonly string[]).includes(p) || rest.length > 3) return fail(usage);
          return { ok: true, next: { ...cur, ai: { ...cur.ai, webProvider: p as Settings["ai"]["webProvider"] } }, message: `AI WEB SEARCH PROVIDER ${p.toUpperCase()} (ITS KEY GOES IN APIKEYS)` };
        }
        if ((w !== "ON" && w !== "OFF") || rest.length > 2) return fail(usage);
        const on = w === "ON";
        return {
          ok: true, next: { ...cur, ai: { ...cur.ai, web: on } },
          message: on
            ? "AI WEB ACCESS ON. WARNING: THE AI CAN NOW SEARCH AND READ PUBLIC WEB PAGES. PAGES ARE WRITTEN BY STRANGERS AND CAN TRY TO MISLEAD IT (PROMPT INJECTION); THEY ARE FENCED OFF AS UNTRUSTED DATA, CAPPED PER ANSWER AND LOGGED IN AUDIT. SEARCH NEEDS A KEY IN APIKEYS"
            : "AI WEB ACCESS OFF",
        };
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
      return fail("SETTINGS STARTUP|TAPE|MODE|THEME|FONT|VIM|CLOCKS|CHART|THOUSANDS|DECIMAL|POLL|SOURCE|AI|KEYS|RESET ...");
  }
}
