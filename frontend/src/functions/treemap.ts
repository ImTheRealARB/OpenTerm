/**
 * IMAP layout maths (pure, no DOM): the squarified treemap of Bruls, Huizing and van Wijk (2000), a two-level version (groups, then tiles),
 * keyboard navigation between tiles and the colour bands. Values that are not positive finite numbers get a zero-size rectangle.
 */

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** One rectangle per input value (same index), tiling `r` exactly with areas proportional to the values. */
export function squarify(values: number[], r: Rect): Rect[] {
  const out: Rect[] = values.map(() => ({ x: r.x, y: r.y, w: 0, h: 0 }));
  const idx: number[] = [];
  let total = 0;
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (v > 0 && Number.isFinite(v)) {
      idx.push(i);
      total += v;
    }
  }
  if (!idx.length || !(r.w > 0) || !(r.h > 0)) return out;
  idx.sort((a, b) => values[b] - values[a]);
  const scale = (r.w * r.h) / total;
  let { x, y, w, h } = r;
  let i = 0;
  while (i < idx.length) {
    const side = Math.min(w, h);
    let end = i;
    let sum = 0;
    let min = Infinity;
    let max = 0;
    let worst = Infinity;
    for (let j = i; j < idx.length; j++) {
      const a = values[idx[j]] * scale;
      const nsum = sum + a;
      const nmin = Math.min(min, a);
      const nmax = Math.max(max, a);
      const nworst = Math.max((side * side * nmax) / (nsum * nsum), (nsum * nsum) / (side * side * nmin));
      if (j > i && nworst > worst) break;
      sum = nsum;
      min = nmin;
      max = nmax;
      worst = nworst;
      end = j + 1;
    }
    if (w >= h) {
      const cw = sum / h; // a column of width cw down the left edge
      let cy = y;
      for (let j = i; j < end; j++) {
        const ch = (values[idx[j]] * scale) / cw;
        out[idx[j]] = { x, y: cy, w: cw, h: ch };
        cy += ch;
      }
      x += cw;
      w -= cw;
    } else {
      const rh = sum / w; // a row of height rh along the top edge
      let cx = x;
      for (let j = i; j < end; j++) {
        const cw = (values[idx[j]] * scale) / rh;
        out[idx[j]] = { x: cx, y, w: cw, h: rh };
        cx += cw;
      }
      y += rh;
      h -= rh;
    }
    i = end;
  }
  return out;
}

export interface TGroup {
  key: string;
  items: { id: number; value: number }[];
}
export interface TGroupRect extends Rect {
  key: string;
  value: number;
  /** Height of the label band at the top of the group (0 when the group is too small for one). */
  header: number;
}
export interface TTile extends Rect {
  id: number;
  /** Index into the groups array. */
  group: number;
}

export function treemap(groups: TGroup[], W: number, H: number, opts: { header: number; pad: number } = { header: 14, pad: 1 }): { groups: TGroupRect[]; tiles: TTile[] } {
  const totals = groups.map((g) => g.items.reduce((s, it) => s + (it.value > 0 && Number.isFinite(it.value) ? it.value : 0), 0));
  const rects = squarify(totals, { x: 0, y: 0, w: W, h: H });
  const outGroups: TGroupRect[] = [];
  const tiles: TTile[] = [];
  groups.forEach((g, gi) => {
    const gr = rects[gi];
    const header = gr.h >= opts.header * 3 && gr.w >= 40 ? opts.header : 0;
    outGroups.push({ ...gr, key: g.key, value: totals[gi], header });
    if (!(gr.w > 0) || !(gr.h > 0)) return;
    const inner = { x: gr.x + opts.pad, y: gr.y + header + opts.pad, w: gr.w - 2 * opts.pad, h: gr.h - header - 2 * opts.pad };
    if (!(inner.w > 0) || !(inner.h > 0)) return;
    const tr = squarify(g.items.map((it) => it.value), inner);
    g.items.forEach((it, k) => {
      if (tr[k].w > 0 && tr[k].h > 0) tiles.push({ ...tr[k], id: it.id, group: gi });
    });
  });
  return { groups: outGroups, tiles };
}

export type Dir = "left" | "right" | "up" | "down";

/** Nearest tile in a direction (centres in that half-plane; being off-axis costs double). Stays on `i` when there is none. */
export function neighbor(tiles: Rect[], i: number, dir: Dir): number {
  const a = tiles[i];
  if (!a) return i;
  const cx = a.x + a.w / 2;
  const cy = a.y + a.h / 2;
  let best = i;
  let bestScore = Infinity;
  for (let j = 0; j < tiles.length; j++) {
    if (j === i) continue;
    const dx = tiles[j].x + tiles[j].w / 2 - cx;
    const dy = tiles[j].y + tiles[j].h / 2 - cy;
    const along = dir === "right" ? dx : dir === "left" ? -dx : dir === "down" ? dy : -dy;
    if (along <= 1e-9) continue;
    const off = dir === "left" || dir === "right" ? Math.abs(dy) : Math.abs(dx);
    const score = along + 2 * off;
    if (score < bestScore) {
      bestScore = score;
      best = j;
    }
  }
  return best;
}

const BAND_EDGES = [0.25, 1, 2, 3];

/** Signed colour band -4..4 of a percent change: 0 = flat (under 0.25%) or no data, 4 = 3% or more. */
export function pctBand(p: number | null | undefined): number {
  if (p == null || !Number.isFinite(p)) return 0;
  const m = Math.abs(p);
  let b = 0;
  for (const e of BAND_EDGES) if (m >= e) b++;
  return p < 0 ? -b : b;
}
