/**
 * Custom font (pure; unit-tested). The user types the NAME of a font installed on their computer ("Fira Code",
 * "Cascadia Mono", "Comic Sans MS"); we never download a font, so the "no web fonts" speed rule still holds.
 *
 * How it reaches the screen: styles.css defines `--font` as `var(--font-user, var(--font-base))`. Setting `--font-user`
 * on <html> changes the font of every DOM panel at once, and canvas code (grids, charts) reads the same `--font`
 * variable, so one setting covers both. The built-in stack stays behind the chosen name as a fallback, so a font that
 * is missing on another computer (settings sync between browsers) degrades to the normal look instead of a serif page.
 */

/** Letters, digits, space and `. _ + -` only: nothing that could break out of a quoted CSS font name. 1-60 characters. */
export const FONT_NAME_RE = /^[\p{L}\p{N}_][\p{L}\p{N}_ .+-]{0,59}$/u;

/** "" means "use the built-in font". */
export const isFontName = (v: unknown): v is string => typeof v === "string" && (v === "" || FONT_NAME_RE.test(v));

/** The CSS `font-family` value for a chosen font: the name first, then the built-in stack. */
export const fontStack = (name: string): string => `"${name}", var(--font-base)`;

/** Sets or clears the custom font on the document. */
export function applyFont(name: string, root: { style: { setProperty(k: string, v: string): void; removeProperty(k: string): void } }): void {
  if (name) root.style.setProperty("--font-user", fontStack(name));
  else root.style.removeProperty("--font-user");
}
