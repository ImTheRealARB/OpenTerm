import type { GridHandle } from "../components/Grid";

/**
 * Grid navigation keys shared by every panel with a table: j/k, arrows, g/G, Home/End, PageUp/PageDown.
 * `skip(i)` marks rows (section headers) the cursor should step over.
 * Returns true when the key was a navigation key (so the caller can stop handling it), false otherwise.
 */
export function navKey(e: KeyboardEvent, g: GridHandle | null, count: number, skip?: (i: number) => boolean): boolean {
  if (!g) return false;
  const step = (d: 1 | -1) => {
    const before = g.selected();
    g.move(d);
    const at = g.selected();
    if (skip?.(at)) {
      g.move(d);
      if (skip(g.selected())) g.moveTo(before); // a header at the very end: stay put
    }
  };
  switch (e.key) {
    case "j":
    case "ArrowDown":
      step(1);
      return true;
    case "k":
    case "ArrowUp":
      step(-1);
      return true;
    case "g":
    case "Home":
      g.moveTo(skip?.(0) ? 1 : 0);
      return true;
    case "G":
    case "End":
      g.moveTo(count - 1);
      return true;
    case "PageDown":
      g.page(1);
      return true;
    case "PageUp":
      g.page(-1);
      return true;
  }
  return false;
}
