/**
 * Themes are CSS variable sets in styles.css: amber is `:root`, the others are `:root[data-theme="name"]`.
 * Switching sets the attribute on <html>, so it applies instantly without a reload. Colours carry
 * meaning only (up / down / stale = warn / error / selection / accent); no other styling changes.
 */
export const THEMES = ["amber", "green", "white", "light"] as const;
export type ThemeName = (typeof THEMES)[number];

export const THEME_LABELS: Record<ThemeName, string> = {
  amber: "AMBER ON BLACK (DEFAULT)",
  green: "GREEN PHOSPHOR",
  white: "HIGH-CONTRAST WHITE",
  light: "LIGHT (DAYLIGHT)",
};

/** Every theme must define all of these (checked by themes.test.ts against styles.css). */
export const COLOR_TOKENS = ["--bg", "--fg", "--fg-dim", "--up", "--down", "--sel", "--accent", "--warn", "--err", "--line"] as const;

export const isTheme = (v: unknown): v is ThemeName => typeof v === "string" && (THEMES as readonly string[]).includes(v);

/** Sets the theme on the document. The default (amber) removes the attribute so `:root` applies. */
export function applyTheme(name: ThemeName, root: { setAttribute(k: string, v: string): void; removeAttribute(k: string): void }): void {
  if (name === "amber") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", name);
}
