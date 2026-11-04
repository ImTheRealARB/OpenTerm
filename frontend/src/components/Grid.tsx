/**
 * Canvas data grid. Virtualized (only visible rows are drawn), fixed character-width columns
 * (no text measuring in hot paths), imperative partial repaints for ticks. No DOM per cell.
 */
import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import { displayVersion } from "../settings/runtime";
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
  /** Repaint just these rows; `frame` enables the one-frame highlight for cells that changed in it. */
  redrawRows(rows: Iterable<number>, frame: number): void;
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

const ROW_H = 16;
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
    colors: { fg: v("--fg"), dim: v("--fg-dim"), up: v("--up"), down: v("--down"), warn: v("--warn"), err: v("--err"), acc: v("--accent"), val: v("--val") || v("--fg") },
  };
}

function clip(s: string, n: number): string {
  return s.length <= n ? s : s.slice(0, Math.max(0, n - 1)) + "…";
}

function GridInner<R>({ columns, rows, initialSelected = 0, onSelect, band }: Props<R>, ref: React.Ref<GridHandle>) {
  const box = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const sr = useRef<HTMLDivElement>(null);
  const st = useRef({ top: 0, sel: initialSelected, w: 0, h: 0, cw: 7, theme: null as Theme | null, ctx: null as CanvasRenderingContext2D | null, xs: [] as number[] });
  const data = useRef({ columns, rows, band });
  data.current = { columns, rows, band };

  const visibleCount = () => Math.max(1, Math.floor((st.current.h - ROW_H) / ROW_H));

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
    const y = ROW_H + vis * ROW_H;
    const { columns: cols, rows: rs, band: isBand } = data.current;
    const row = rs[i];
    const banded = row !== undefined && !!isBand?.(row);
    ctx.fillStyle = i === s.sel ? th.sel : banded ? th.hdrBg : th.bg;
    ctx.fillRect(0, y, s.w, ROW_H);
    if (row === undefined) return;
    if (i !== s.sel && !banded) {
      // Thin gray rules: under the row and between columns (no per-cell allocation, plain rects).
      ctx.fillStyle = th.rowRule;
      ctx.fillRect(0, y + ROW_H - 1, s.w, 1);
      ctx.fillStyle = th.colRule;
      for (let c = 1; c < cols.length; c++) ctx.fillRect(s.xs[c] - 1, y, 1, ROW_H - 1);
    }
    for (let c = 0; c < cols.length; c++) {
      const col = cols[c];
      const x = s.xs[c];
      const cwPx = col.width * s.cw + PAD * 2;
      const hl = frame >= 0 && col.flash ? col.flash(row, frame) : null;
      if (hl) {
        ctx.fillStyle = th.colors[hl];
        ctx.fillRect(x + 1, y + 1, cwPx - 2, ROW_H - 2);
      }
      const text = clip(col.text(row), col.width);
      ctx.fillStyle = hl ? th.bg : banded ? (c === 0 ? th.colors.fg : th.colors.val) : th.colors[col.color?.(row) ?? (col.align === "right" ? "val" : "fg")];
      const tx = col.align === "right" ? x + PAD + (col.width - text.length) * s.cw : x + PAD;
      ctx.fillText(text, tx, y + ROW_H / 2 + 1);
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
    const trackH = s.h - ROW_H;
    const thumbH = Math.max(8, (vc / n) * trackH);
    const y = ROW_H + (s.top / (n - vc)) * (trackH - thumbH);
    ctx.fillStyle = s.theme.bg;
    ctx.fillRect(s.w - 3, ROW_H, 3, trackH);
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
    ctx.fillRect(0, 0, s.w, ROW_H - 1);
    ctx.fillStyle = th.hdr;
    for (let c = 0; c < cols.length; c++) {
      const col = cols[c];
      const t = clip(col.title, col.width);
      const tx = col.align === "right" ? s.xs[c] + PAD + (col.width - t.length) * s.cw : s.xs[c] + PAD;
      ctx.fillText(t, tx, ROW_H / 2 + 1);
    }
    ctx.fillStyle = th.line;
    ctx.fillRect(0, ROW_H - 1, s.w, 1);
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
    redrawRows(list, frame) {
      const flashed: number[] = [];
      for (const i of list) {
        drawRow(i, frame);
        flashed.push(i);
      }
      // One-frame highlight: repaint plain on the next frame.
      if (flashed.length && frame >= 0) requestAnimationFrame(() => flashed.forEach((i) => drawRow(i, -1)));
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
      const i = s.top + Math.floor((e.clientY - r.top - ROW_H) / ROW_H);
      if (e.clientY - r.top > ROW_H) moveTo(i);
    };
    cv.addEventListener("wheel", onWheel, { passive: false });
    cv.addEventListener("mousedown", onDown);
    return () => {
      ro.disconnect();
      cv.removeEventListener("wheel", onWheel);
      cv.removeEventListener("mousedown", onDown);
    };
  }, []);

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
