/**
 * IMAP canvas painting (no React, no network): one pass over the tiles, state changes kept to a minimum.
 * Colour carries one meaning only: up / down theme colours, stronger for a bigger move (see `pctBand`). Flat or no data is the neutral fill.
 */
import { pctBand, type TGroupRect, type TTile } from "./treemap";

export interface PaintColors {
  bg: string;
  fg: string;
  dim: string;
  up: string;
  down: string;
  sel: string;
  line: string;
  font: string;
}

/** Fill opacity by |band| 0..4. */
export const BAND_ALPHA = [0, 0.2, 0.4, 0.62, 0.85];
export const BAND_LABELS = ["-3%+", "-2%", "-1%", "-0.25%", "FLAT", "+0.25%", "+1%", "+2%", "+3%+"];
const CHAR_W = 6.6; // 11 px monospace, close enough for a fit test without measureText per tile

export interface PaintRow {
  sym: string;
  pct: number | null;
}

const fmt = (p: number) => `${p >= 0 ? "+" : ""}${p.toFixed(1)}%`;

export function paintTreemap(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  layout: { groups: TGroupRect[]; tiles: TTile[] },
  rows: PaintRow[],
  colors: PaintColors,
  selectedId: number | null,
): void {
  ctx.globalAlpha = 1;
  ctx.fillStyle = colors.bg;
  ctx.fillRect(0, 0, w, h);
  ctx.font = `11px ${colors.font}`;
  ctx.textBaseline = "alphabetic";
  // Fills batched by colour band: nine fill-style changes and nine fills instead of one of each per tile.
  const byBand: TTile[][] = Array.from({ length: 9 }, () => []);
  for (const t of layout.tiles) byBand[pctBand(rows[t.id]?.pct) + 4].push(t);
  for (let bi = 0; bi < 9; bi++) {
    const list = byBand[bi];
    if (!list.length) continue;
    const band = bi - 4;
    if (band === 0) {
      ctx.globalAlpha = 1;
      ctx.fillStyle = colors.sel;
    } else {
      ctx.globalAlpha = BAND_ALPHA[Math.abs(band)];
      ctx.fillStyle = band > 0 ? colors.up : colors.down;
    }
    ctx.beginPath();
    for (const t of list) {
      if (t.w > 3 && t.h > 3) ctx.rect(t.x + 0.5, t.y + 0.5, t.w - 1, t.h - 1);
      else ctx.rect(t.x, t.y, t.w, t.h);
    }
    ctx.fill();
  }
  ctx.globalAlpha = 1;
  ctx.fillStyle = colors.fg;
  for (const t of layout.tiles) {
    const row = rows[t.id];
    if (!row || t.h < 14 || t.w < row.sym.length * CHAR_W + 6) continue;
    ctx.fillText(row.sym, t.x + 3, t.y + 11);
    if (t.h >= 26 && row.pct != null && t.w >= 8 * CHAR_W) ctx.fillText(fmt(row.pct), t.x + 3, t.y + 23);
  }
  ctx.strokeStyle = colors.line;
  ctx.lineWidth = 1;
  for (const g of layout.groups) {
    if (!(g.w > 0) || !(g.h > 0)) continue;
    ctx.strokeRect(g.x + 0.5, g.y + 0.5, g.w - 1, g.h - 1);
    if (g.header > 0) {
      ctx.fillStyle = colors.dim;
      const max = Math.max(0, Math.floor((g.w - 6) / CHAR_W));
      const name = g.key.toUpperCase();
      ctx.fillText(name.length > max ? `${name.slice(0, Math.max(0, max - 1))}…` : name, g.x + 3, g.y + 11);
    }
  }
  if (selectedId !== null) {
    const t = layout.tiles.find((x) => x.id === selectedId);
    if (t) {
      ctx.strokeStyle = colors.fg;
      ctx.lineWidth = 2;
      ctx.strokeRect(t.x + 1, t.y + 1, Math.max(1, t.w - 2), Math.max(1, t.h - 2));
    }
  }
}
