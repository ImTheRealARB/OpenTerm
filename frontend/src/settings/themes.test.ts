import { describe, expect, it } from "vitest";
import { COLOR_TOKENS, THEMES, THEME_LABELS, applyTheme, isTheme } from "./themes";

// vitest blanks CSS imports (even ?raw) and the project has no @types/node, so read the file through Node directly.
const nodeFs = (globalThis as unknown as { process: { getBuiltinModule(id: string): { readFileSync(p: URL, enc: string): string } } }).process.getBuiltinModule("node:fs");
const css = nodeFs.readFileSync(new URL("../styles.css", import.meta.url), "utf8");

/** Token values of one theme block; `amber` is the plain :root block. */
function tokens(theme: string): Record<string, string> {
  const sel = theme === "amber" ? /:root\s*\{([^}]*)\}/ : new RegExp(`:root\\[data-theme="${theme}"\\]\\s*\\{([^}]*)\\}`);
  const body = sel.exec(css)?.[1] ?? "";
  const out: Record<string, string> = {};
  for (const m of body.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) out[m[1]] = m[2].trim();
  return out;
}

const lum = (hex: string) => {
  const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
};
const contrast = (a: string, b: string) => {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};

describe("themes", () => {
  it("lists the four themes with labels", () => {
    expect([...THEMES]).toEqual(["amber", "green", "white", "light"]);
    for (const t of THEMES) expect(THEME_LABELS[t]).toBeTruthy();
    expect(isTheme("green")).toBe(true);
    expect(isTheme("Green")).toBe(false);
    expect(isTheme(undefined)).toBe(false);
  });

  it.each([...THEMES])("%s defines every colour token as a hex colour", (t) => {
    const v = tokens(t);
    for (const k of COLOR_TOKENS) expect(v[k], `${t} ${k}`).toMatch(/^#[0-9a-f]{6}$/i);
  });

  it("up and down stay distinct in every theme", () => {
    for (const t of THEMES) {
      const v = tokens(t);
      expect(v["--up"].toLowerCase()).not.toBe(v["--down"].toLowerCase());
    }
  });

  it.each([...THEMES])("%s keeps text readable (fg 7:1, dim fg 4.5:1 on the background)", (t) => {
    const v = tokens(t);
    expect(contrast(v["--fg"], v["--bg"])).toBeGreaterThanOrEqual(7);
    expect(contrast(v["--fg-dim"], v["--bg"])).toBeGreaterThanOrEqual(4.5 - 0.0001);
  });

  it("white is the high-contrast theme", () => {
    const v = tokens("white");
    expect(contrast(v["--fg"], v["--bg"])).toBeGreaterThanOrEqual(15);
  });

  it("applyTheme sets the attribute, and amber clears it", () => {
    const attrs = new Map<string, string>();
    const root = { setAttribute: (k: string, v: string) => attrs.set(k, v), removeAttribute: (k: string) => attrs.delete(k) };
    applyTheme("green", root);
    expect(attrs.get("data-theme")).toBe("green");
    applyTheme("amber", root);
    expect(attrs.has("data-theme")).toBe(false);
  });
});
