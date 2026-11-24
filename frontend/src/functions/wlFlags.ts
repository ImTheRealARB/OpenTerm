/**
 * Watchlist colour flags and section headers (Phase 22), the pure part: no React, no network, so vitest covers it.
 *
 * The server stores them beside the list (backend `wlmeta.py`, kv `wlmeta:<NAME>`) as
 *   { flags: { AAPL: "RED" }, sections: [{ before: "JPM", title: "Banks" }] }
 * and this file turns that document plus the quote rows into what the grid shows, and applies one edit to it.
 */
import type { Column } from "../components/Grid";
import type { WlMeta } from "../net/types";

/** The 7 flag colours, in the order the F key cycles them. Mirror of backend `wlmeta.COLORS` (`test_ts_mirrors.py`). */
export const FLAG_COLORS = ["RED", "ORANGE", "YELLOW", "GREEN", "BLUE", "PURPLE", "GREY"] as const;
export type FlagColor = (typeof FLAG_COLORS)[number];

/**
 * What each flag paints. Fixed colours rather than theme tokens: a flag's colour IS its meaning (the user chose "red = sell
 * list"), so it must not change when the theme does. Picked to stay distinct on a black or a light background.
 */
export const FLAG_HEX: Readonly<Record<FlagColor, string>> = {
  RED: "#e5484d", ORANGE: "#f2862f", YELLOW: "#e6c229", GREEN: "#3fb950", BLUE: "#3d8bfd", PURPLE: "#a371f7", GREY: "#8b8b8b",
};

export const EMPTY_META: WlMeta = { flags: {}, sections: [] };

/** none -> RED -> ORANGE ... -> GREY -> none (the F key). */
export function nextFlag(cur: string | undefined): FlagColor | undefined {
  const i = cur ? FLAG_COLORS.indexOf(cur as FlagColor) : -1;
  return i === FLAG_COLORS.length - 1 ? undefined : FLAG_COLORS[i + 1];
}

/** ALL -> each colour that is in use -> ALL (Shift+F). Colours nobody used are skipped: an empty filter shows nothing useful. */
export function nextFilter(cur: FlagColor | null, meta: WlMeta): FlagColor | null {
  const used = FLAG_COLORS.filter((c) => Object.values(meta.flags).includes(c));
  const i = cur ? used.indexOf(cur) : -1;
  return i + 1 < used.length ? used[i + 1] : null;
}

/** One edit, as typed (`WL TECH FLAG AAPL RED`, `WL TECH SECTION JPM Banks`) or from a panel key. */
export type MetaChange = { kind: "flag"; symbol: string; color?: FlagColor } | { kind: "section"; before: string; title?: string };

/** The document after one edit. A missing colour / title removes the flag / header. Never mutates `meta`. */
export function applyMetaChange(meta: WlMeta, ch: MetaChange): WlMeta {
  if (ch.kind === "flag") {
    const flags = { ...meta.flags };
    if (ch.color) flags[ch.symbol] = ch.color;
    else delete flags[ch.symbol];
    return { flags, sections: meta.sections };
  }
  const rest = meta.sections.filter((s) => s.before !== ch.before);
  return { flags: meta.flags, sections: ch.title ? [...rest, { before: ch.before, title: ch.title }] : rest };
}

/** A grid row: a quote row, or a section header band (no symbol, never live, never exported). */
export type Sectioned<R> = R | { section: string };
export const isSection = <R,>(r: Sectioned<R>): r is { section: string } => typeof r === "object" && r !== null && "section" in r;

/**
 * The rows the grid shows. With a colour filter only that colour's rows remain. Section headers are shown only in the list's
 * own order (`inOrder`): after a sort by %CHG a "Banks" header above a random row would be a lie. `symbolOf` gives the
 * stored symbol of a row (the list's `input`, which is what flags and sections are keyed on).
 */
export function buildRows<R>(rows: R[], meta: WlMeta, symbolOf: (r: R) => string, filter: FlagColor | null, inOrder: boolean): Sectioned<R>[] {
  const kept = filter ? rows.filter((r) => meta.flags[symbolOf(r)] === filter) : rows;
  if (!inOrder || !meta.sections.length) return kept;
  const titles = new Map(meta.sections.map((s) => [s.before, s.title]));
  const out: Sectioned<R>[] = [];
  for (const r of kept) {
    const t = titles.get(symbolOf(r));
    if (t) out.push({ section: t });
    out.push(r);
  }
  return out;
}

/**
 * The quote columns, taught to draw a section band: the band's title in the first column, nothing in the others, and no
 * flash or graphic (a header has no price). Every function that takes a row is wrapped, so no column ever sees a header.
 */
export function sectionColumns<R>(cols: Column<R>[]): Column<Sectioned<R>>[] {
  return cols.map((c, i) => ({
    ...c,
    text: (r) => (isSection(r) ? (i === 0 ? r.section : "") : c.text(r)),
    color: (r) => (isSection(r) ? "acc" : (c.color?.(r) ?? "fg")),
    flash: c.flash && ((r, f) => (isSection(r) ? null : c.flash!(r, f))),
    draw: c.draw && ((ctx, r, ...rest) => (isSection(r) ? undefined : c.draw!(ctx, r, ...rest))),
  }));
}

/** A narrow first column with the row's flag as a filled square (`aux`: left out of the screen-reader text and CSV). */
export function flagColumn<R>(meta: WlMeta, symbolOf: (r: R) => string): Column<Sectioned<R>> {
  return {
    title: "",
    width: 2,
    aux: true,
    text: () => "",
    draw: (ctx, r, x, y, _w, h) => {
      if (isSection(r)) return;
      const c = meta.flags[symbolOf(r)] as FlagColor | undefined;
      if (!c) return;
      ctx.fillStyle = FLAG_HEX[c];
      const s = Math.max(4, Math.round(h * 0.5));
      ctx.fillRect(x + 2, y + Math.round((h - s) / 2), s, s);
    },
  };
}
