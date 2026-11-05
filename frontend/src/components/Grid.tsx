/**
 * Canvas data grid. Virtualized (only visible rows are drawn), fixed character-width columns
 * (no text measuring in hot paths), imperative partial repaints for ticks. No DOM per cell.
 */
import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import { displayVersion } from "../settings/runtime";
import { registerPanelKeys } from "../keys/panelKeys";
import { usePanelId } from "../state/panelContext";
import type { TipCtx } from "../gui/gridTips";
import { bitClear, bitGrow, bitHas, bitSet } from "../state/bitset";
import { wheelTop } from "../state/gridScroll";
import "./dataColors.css";

/** `val` is the data-value colour (white on the dark themes); uncoloured right-aligned cells use it. */
export type CellColor = "fg" | "dim" | "up" | "down" | "warn" | "err" | "acc" | "val";

export interface Column<R> {
  title: string;
  /** Width in characters. */
  width: number;
  align?: "left" | "right";
  text: (row: R) => string;
  color?: (row: R) => CellColor;
  /** Returns a colour when this cell changed in `frame` (one-frame tick highlight). */
  flash?: (row: R, frame: number) => CellColor | null;
}

export interface GridHandle {
  redraw(): void;
  /**
   * Repaint the rows whose bit is set in `dirty` (a bitset, one bit per row position) that are on screen, then clear `dirty`.
   * `frame` enables the one-frame highlight for cells that changed in it.
   */
  redrawDirty(dirty: Uint32Array, frame: number): void;
  move(delta: number): void;
  moveTo(index: number): void;
  page(dir: 1 | -1): void;
  selected(): number;
}

interface Props<R> {
  columns: Column<R>[];
  rows: R[];
  initialSelected?: number;
  onSelect?: (index: number) => void;
  /** Rows drawn as a full-width section band (e.g. board section headers). */
  band?: (row: R) => boolean;
}

/** Terminal row height; GUI mode raises it through the CSS variable `--row` (read into the theme, see `rowH`). */
const DEFAULT_ROW_H = 16;
const PAD = 6;

interface Theme {
  bg: string;
  sel: string;
  line: string;
  bar: string;
  hdr: string;
  hdrBg: string;
  rowRule: string;
  colRule: string;
  font: string;
  /** Row height in CSS px, from `--row` (Terminal 16, GUI 20). */
  rowH: number;
  colors: Record<CellColor, string>;
}

function readTheme(el: Element): Theme {
  const cs = getComputedStyle(el);
  const v = (n: string) => cs.getPropertyValue(n).trim();
  return {
    bg: v("--bg"),
    sel: v("--grid-sel") || v("--sel"),
    line: v("--line"),
    bar: v("--bar") || v("--sel"),
    hdr: v("--grid-hdr-fg") || v("--hdr") || v("--fg-dim"),
    hdrBg: v("--grid-hdr-bg") || v("--bar") || v("--sel"),
    rowRule: v("--grid-row-rule") || v("--line"),
    colRule: v("--grid-col-rule") || v("--line"),
    font: `${v("--fs") || "12px"} ${v("--font")}`,
    rowH: parseFloat(v("--row")) || DEFAULT_ROW_H,
    colors: { fg: v("--fg"), dim: v("--fg-dim"), up: v("--up"), down: v("--down"), warn: v("--warn"), err: v("--err"), acc: v("--accent"), val: v("--val") || v("--fg") },
  };
}

function clip(s: string, n: number): string {
  return s.length <= n ? s : s.slice(0, Math.max(0, n - 1)) + "…";
}

function GridInner<R>({ columns, rows, initialSelected = 0, onSelect, band }: Props<R>, ref: React.Ref<GridHandle>) {
  const panelId = usePanelId();
  const box = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const sr = useRef<HTMLDivElement>(null);
  const st = useRef({ top: 0, sel: initialSelected, w: 0, h: 0, cw: 7, theme: null as Theme | null, ctx: null as CanvasRenderingContext2D | null, xs: [] as number[] });
  // Current row height. A function, not a constant: the theme (and so the height) is re-read when the display settings change.
  const ROW_H_NOW = () => st.current.theme?.rowH ?? DEFAULT_ROW_H;
  const data = useRef({ columns, rows, band });
  data.current = { columns, rows, band };

  // Rows currently painted with the one-frame highlight, as a bitset (`bits`); `end` = 1 + highest row that may be set.
  const flash = useRef({ bits: new Uint32Array(0) as Uint32Array, end: 0, scheduled: false });
  /** Prebuilt once (no closure per frame): repaints every highlighted row plain and clears the bitset. */
  const unflash = useRef<() => void>(() => undefined);
  unflash.current = () => {
    const fl = flash.current;
    fl.scheduled = false;
    for (let i = 0; i < fl.end; i++) {
      if (!bitHas(fl.bits, i)) continue;
      bitClear(fl.bits, i);
      drawRow(i, -1);
    }
    fl.end = 0;
  };

  const visibleCount = () => Math.max(1, Math.floor((st.current.h - ROW_H_NOW()) / ROW_H_NOW()));

  const layout = () => {
    const s = st.current;
    let x = 0;
    s.xs = data.current.columns.map((c) => {
      const at = x;
      x += c.width * s.cw + PAD * 2;
      return at;
    });
  };

  const drawRow = (i: number, frame: number) => {
    const s = st.current;
    const ctx = s.ctx;
    const th = s.theme;
    if (!ctx || !th) return;
    const vis = i - s.top;
    if (vis < 0 || vis >= visibleCount()) return;
    const y = ROW_H_NOW() + vis * ROW_H_NOW();
    const { columns: cols, rows: rs, band: isBand } = data.current;
    const row = rs[i];
    const banded = row !== undefined && !!isBand?.(row);
    ctx.fillStyle = i === s.sel ? th.sel : banded ? th.hdrBg : th.bg;
    ctx.fillRect(0, y, s.w, ROW_H_NOW());
    if (row === undefined) return;
    if (i !== s.sel && !banded) {
      // Thin gray rules: under the row and between columns (no per-cell allocation, plain rects).
      ctx.fillStyle = th.rowRule;
      ctx.fillRect(0, y + ROW_H_NOW() - 1, s.w, 1);
      ctx.fillStyle = th.colRule;
      for (let c = 1; c < cols.length; c++) ctx.fillRect(s.xs[c] - 1, y, 1, ROW_H_NOW() - 1);
    }
    for (let c = 0; c < cols.length; c++) {
      const col = cols[c];
      const x = s.xs[c];
      const cwPx = col.width * s.cw + PAD * 2;
      const hl = frame >= 0 && col.flash ? col.flash(row, frame) : null;
      if (hl) {
        ctx.fillStyle = th.colors[hl];
        ctx.fillRect(x + 1, y + 1, cwPx - 2, ROW_H_NOW() - 2);
      }
      const text = clip(col.text(row), col.width);
      ctx.fillStyle = hl ? th.bg : banded ? (c === 0 ? th.colors.fg : th.colors.val) : th.colors[col.color?.(row) ?? (col.align === "right" ? "val" : "fg")];
      const tx = col.align === "right" ? x + PAD + (col.width - text.length) * s.cw : x + PAD;
      ctx.fillText(text, tx, y + ROW_H_NOW() / 2 + 1);
    }
  };

  /** Canvas is invisible to screen readers: mirror the selected row as text (on selection change only). */
  const describe = () => {
    const el = sr.current;
    const row = data.current.rows[st.current.sel];
    if (!el) return;
    const text = row === undefined ? "" : data.current.columns.map((c) => `${c.title} ${c.text(row)}`.trim()).join(" · ");
    if (el.textContent !== text) el.textContent = text; // identical text would still re-announce in the live region
  };

  const drawScrollbar = () => {
    const s = st.current;
    const ctx = s.ctx;
    const n = data.current.rows.length;
    const vc = visibleCount();
    if (!ctx || !s.theme || n <= vc) return;
    const trackH = s.h - ROW_H_NOW();
    const thumbH = Math.max(8, (vc / n) * trackH);
    const y = ROW_H_NOW() + (s.top / (n - vc)) * (trackH - thumbH);
    ctx.fillStyle = s.theme.bg;
    ctx.fillRect(s.w - 3, ROW_H_NOW(), 3, trackH);
    ctx.fillStyle = s.theme.colors.dim;
    ctx.fillRect(s.w - 3, y, 3, thumbH);
  };

  const redraw = () => {
    const s = st.current;
    const ctx = s.ctx;
    const th = s.theme;
    if (!ctx || !th) return;
    ctx.fillStyle = th.bg;
    ctx.fillRect(0, 0, s.w, s.h);
    const cols = data.current.columns;
    ctx.fillStyle = th.hdrBg;
    ctx.fillRect(0, 0, s.w, ROW_H_NOW() - 1);
    ctx.fillStyle = th.hdr;
    for (let c = 0; c < cols.length; c++) {
      const col = cols[c];
      const t = clip(col.title, col.width);
      const tx = col.align === "right" ? s.xs[c] + PAD + (col.width - t.length) * s.cw : s.xs[c] + PAD;
      ctx.fillText(t, tx, ROW_H_NOW() / 2 + 1);
    }
    ctx.fillStyle = th.line;
    ctx.fillRect(0, ROW_H_NOW() - 1, s.w, 1);
    const end = Math.min(data.current.rows.length, s.top + visibleCount());
    for (let i = s.top; i < end; i++) drawRow(i, -1);
    drawScrollbar();
  };

  const clampTop = () => {
    const s = st.current;
    const n = data.current.rows.length;
    const vc = visibleCount();
    if (s.sel < s.top) s.top = s.sel;
    if (s.sel >= s.top + vc) s.top = s.sel - vc + 1;
    s.top = Math.max(0, Math.min(s.top, Math.max(0, n - vc)));
  };

  const moveTo = (i: number) => {
    const s = st.current;
    const n = data.current.rows.length;
    if (!n) return;
    const next = Math.max(0, Math.min(n - 1, i));
    if (next === s.sel) return;
    const prevTop = s.top;
    const prevSel = s.sel;
    s.sel = next;
    clampTop();
    if (s.top !== prevTop) redraw();
    else {
      drawRow(prevSel, -1);
      drawRow(next, -1);
    }
    describe();
    onSelect?.(next);
  };

  useImperativeHandle(ref, () => ({
    redraw,
    redrawDirty(dirty, frame) {
      const s = st.current;
      const end = Math.min(data.current.rows.length, s.top + visibleCount());
      // Only the visible rows can be painted, so only they are tested. Off-screen dirty bits are simply dropped.
      const fl = flash.current;
      fl.bits = bitGrow(fl.bits, end);
      let any = false;
      for (let i = s.top; i < end; i++) {
        if (!bitHas(dirty, i)) continue;
        drawRow(i, frame);
        any = true;
        if (frame >= 0) {
          bitSet(fl.bits, i);
          fl.end = Math.max(fl.end, i + 1);
        }
      }
      dirty.fill(0);
      // One-frame highlight: repaint plain on the next frame. ONE prebuilt callback, scheduled at most once.
      if (any && frame >= 0 && !fl.scheduled) {
        fl.scheduled = true;
        requestAnimationFrame(unflash.current);
      }
    },
    move: (d) => moveTo(st.current.sel + d),
    moveTo,
    page: (dir) => moveTo(st.current.sel + dir * visibleCount()),
    selected: () => st.current.sel,
  }));

  useEffect(() => {
    const el = box.current!;
    const cv = canvas.current!;
    const s = st.current;
    s.theme = readTheme(el);
    s.ctx = cv.getContext("2d", { alpha: false });
    const resize = () => {
      const dpr = window.devicePixelRatio || 1;
      s.w = el.clientWidth;
      s.h = el.clientHeight;
      cv.width = Math.max(1, Math.floor(s.w * dpr));
      cv.height = Math.max(1, Math.floor(s.h * dpr));
      cv.style.width = `${s.w}px`;
      cv.style.height = `${s.h}px`;
      const ctx = s.ctx!;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.font = s.theme!.font;
      ctx.textBaseline = "middle";
      s.cw = ctx.measureText("0").width; // once per resize, never per cell
      layout();
      clampTop();
      redraw();
    };
    const ro = new ResizeObserver(resize);
    ro.observe(el);
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const top = wheelTop(s.top, e.deltaY, data.current.rows.length, visibleCount());
      if (top === s.top) return; // at either end, or a horizontal wheel: nothing moved, nothing to repaint
      s.top = top;
      redraw();
    };
    const onDown = (e: MouseEvent) => {
      const r = cv.getBoundingClientRect();
      const i = s.top + Math.floor((e.clientY - r.top - ROW_H_NOW()) / ROW_H_NOW());
      if (e.clientY - r.top > ROW_H_NOW()) moveTo(i);
    };
    // GUI mode only: header hover shows the glossary tip (lazy chunk, which owns the logic). Terminal mode returns on the first line.
    const tip = { at: -1, i: -1, hasTips: null as boolean | null };
    const tipCtx = (): TipCtx => ({ tip, cv, xs: s.xs, cw: s.cw, pad: PAD, rowH: ROW_H_NOW(), cols: data.current.columns, panel: box.current?.closest(".panel") ?? null });
    const onMove = (e: MouseEvent) => {
      if (document.documentElement.dataset.mode === "gui") void import("../gui/gridTips").then((m) => m.headerMove(e, tipCtx()));
    };
    const onLeave = () => {
      if (tip.at >= 0) void import("../gui/gridTips").then((m) => m.headerLeave(tipCtx()));
    };
    cv.addEventListener("wheel", onWheel, { passive: false });
    cv.addEventListener("mousedown", onDown);
    cv.addEventListener("mousemove", onMove);
    cv.addEventListener("mouseleave", onLeave);
    return () => {
      cv.removeEventListener("mousemove", onMove);
      cv.removeEventListener("mouseleave", onLeave);
      ro.disconnect();
      cv.removeEventListener("wheel", onWheel);
      cv.removeEventListener("mousedown", onDown);
    };
  }, []);

  // GUI mode: Shift+T steps through the columns that have a glossary line and shows each one's tip (Esc hides it).
  // `hasTips` is unknown until the lazy chunk has run once; after that a grid with no glossary column lets T fall through.
  const tipKeys = useRef({ at: -1, i: -1, hasTips: null as boolean | null });
  useEffect(() => {
    const tip = tipKeys.current;
    return registerPanelKeys(panelId, (e) => {
      if (e.key !== "T" || e.ctrlKey || e.altKey || e.metaKey || document.documentElement.dataset.mode !== "gui" || tip.hasTips === false) return false;
      const s = st.current;
      void import("../gui/gridTips").then((m) =>
        m.nextTip({ tip, cv: canvas.current!, xs: s.xs, cw: s.cw, pad: PAD, rowH: ROW_H_NOW(), cols: data.current.columns, panel: box.current?.closest(".panel") ?? null }),
      );
      return true;
    });
  }, [panelId]);

  // Phase 10: theme or number format changed. Re-read the CSS variables once and repaint (never per frame).
  useEffect(
    () =>
      displayVersion.subscribe(() => {
        const s = st.current;
        if (!box.current || !s.ctx) return;
        s.theme = readTheme(box.current);
        s.ctx.font = s.theme.font;
        s.cw = s.ctx.measureText("0").width;
        layout();
        clampTop();
        redraw();
      }),
    [],
  );

  // New rows or columns from React: relayout and repaint once.
  useEffect(() => {
    const s = st.current;
    if (s.sel >= rows.length) s.sel = Math.max(0, rows.length - 1);
    layout();
    clampTop();
    redraw();
    describe();
  }, [rows, columns]);

  return (
    <div ref={box} className="grid" data-rows={rows.length}>
      <canvas ref={canvas} aria-hidden="true" />
      <div ref={sr} className="sr" role="status" aria-live="polite" />
    </div>
  );
}

export const Grid = forwardRef(GridInner) as <R>(p: Props<R> & { ref?: React.Ref<GridHandle> }) => React.ReactElement;
