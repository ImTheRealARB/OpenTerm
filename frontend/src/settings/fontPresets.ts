/**
 * Font presets (pure; unit-tested). `Settings.font` stores a preset `name` (or any other installed font's name for a custom
 * choice); "" is the default, JetBrains Mono. Bundled presets ship as files in public/fonts and are declared in fonts.css;
 * "system" presets use a font the computer must already have (Monaco and Menlo ship with macOS, Consolas with Windows).
 */
export interface FontPreset {
  /** What is stored in settings and what `SETTINGS FONT <name>` takes. */
  name: string;
  /** Shown in menus and the SETTINGS panel. */
  label: string;
  /** CSS `font-family` value. */
  stack: string;
  /** True when the font is not bundled, so it can be missing on this computer (checked, and a warning is shown). */
  system: boolean;
  /** Extra words accepted on the command line, besides the name: `SETTINGS FONT github`. */
  aliases?: string[];
}

const NAMED = (n: string) => `"${n}", var(--font-base)`;

export const FONT_PRESETS: readonly FontPreset[] = [
  { name: "", label: "JetBrains Mono (default)", stack: "var(--font-base)", system: false, aliases: ["default", "jetbrains", "jetbrainsmono"] },
  {
    name: "GitHub Mono", label: "GitHub Mono", system: false, aliases: ["github"],
    stack: 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace',
  },
  { name: "Geist Mono", label: "Geist Mono", stack: NAMED("Geist Mono"), system: false, aliases: ["geist"] },
  { name: "Fira Code", label: "Fira Code", stack: NAMED("Fira Code"), system: false, aliases: ["fira"] },
  { name: "Mononoki", label: "Mononoki", stack: NAMED("Mononoki"), system: false },
  { name: "Hack", label: "Hack", stack: NAMED("Hack"), system: false },
  { name: "Monaco", label: "Monaco (macOS)", stack: NAMED("Monaco"), system: true },
  { name: "DejaVu Sans Mono", label: "DejaVu Sans Mono", stack: NAMED("DejaVu Sans Mono"), system: false, aliases: ["dejavu"] },
  { name: "Menlo", label: "Menlo (macOS)", stack: NAMED("Menlo"), system: true },
  { name: "Consolas", label: "Consolas (Windows)", stack: NAMED("Consolas"), system: true },
  { name: "Bergoom", label: "Bergoom (Bloomberg-style)", stack: NAMED("Bergoom"), system: false, aliases: ["bloomberg"] },
  { name: "Comic Sans MS", label: "Comic Sans (joke)", stack: NAMED("Comic Sans MS"), system: true, aliases: ["comicsans", "comic"] },
];

/** Lower-case letters and digits only, so "Geist Mono", "geist-mono" and "GEISTMONO" all match. */
const key = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, "");

/** The preset a typed name or stored setting refers to, if any. */
export function findPreset(input: string): FontPreset | undefined {
  const k = key(input);
  if (!k) return undefined;
  return FONT_PRESETS.find((p) => key(p.name) === k || (p.aliases ?? []).some((a) => key(a) === k));
}

/** Next or previous preset (wrapping). A custom, non-preset font starts the cycle from the default. */
export function cyclePreset(current: string, dir: 1 | -1): FontPreset {
  const found = current === "" ? FONT_PRESETS[0] : findPreset(current);
  const from = found ? FONT_PRESETS.indexOf(found) : 0;
  return FONT_PRESETS[(from + dir + FONT_PRESETS.length) % FONT_PRESETS.length];
}

/** Menu text for a stored font: a preset's label, or the custom name itself. */
export const fontLabel = (name: string): string => (name === "" ? FONT_PRESETS[0].label : (findPreset(name)?.label ?? name));
