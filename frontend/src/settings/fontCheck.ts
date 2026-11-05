/**
 * Is a font installed on this computer? Browsers do not offer a direct "is it installed" call, so we use the classic
 * width trick: draw the same text in `"Name", <generic>` and in the bare generic. If the named font is missing, the browser
 * silently uses the generic and both widths are identical. We try three generics (monospace, serif, sans-serif) so a
 * font that happens to match one of them is still caught by another. Browser only (needs a canvas); the pure rules live in `font.ts`.
 */
const GENERICS = ["monospace", "serif", "sans-serif"] as const;
// Letters of very different widths, so any two fonts almost certainly differ somewhere in the string.
const SAMPLE = "mmmmmmmmmmlli1WwOo0@#%";

export function fontInstalled(name: string): boolean {
  const ctx = document.createElement("canvas").getContext("2d");
  if (!ctx) throw new Error("canvas is not available, cannot check fonts");
  const width = (family: string): number => {
    ctx.font = `72px ${family}`;
    return ctx.measureText(SAMPLE).width;
  };
  return GENERICS.some((g) => width(`"${name}", ${g}`) !== width(g));
}
