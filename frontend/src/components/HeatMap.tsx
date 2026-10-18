/**
 * Cell map on a canvas (Phase 14: IV surface, option scenario grid). One hue; intensity is the only encoding, so the colour carries the
 * value (spec: colour carries meaning). Rows are `y` labels, columns are the numeric `x` axis. Arrow keys / hjkl move a cursor and the
 * cursor cell is mirrored as text for screen readers and tests, like the Grid. Drawn once per data, cursor or theme change.
 */
import { useEffect, useImperativeHandle, useRef, forwardRef } from "react";
import { displayVersion } from "../settings/runtime";
import { heatLevel, heatRange, heatText, type HeatPayload } from "../research/chartMath";

const CELL_H = 18;
const LABEL_W = 92;
const HEAD_H = 18;

export interface HeatHandle {
  move(dRow: number, dCol: number): void;
}

function readColors(el: Element) {
  const cs = getComputedStyle(el);
  const v = (n: string) => cs.getPropertyValue(n).trim();
  return { bg: v("--bg"), fg: v("--fg"), dim: v("--fg-dim"), line: v("--line"), hue: v("--accent"), font: `${v("--fs") || "12px"} ${v("--font")}` };
}

function HeatMapInner({ heat }: { heat: HeatPayload }, ref: React.Ref<HeatHandle>) {
  const box = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const sr = useRef<HTMLDivElement>(null);
  const st = useRef({ row: 0, col: 0 });
  const latest = useRef(heat);
  latest.current = heat;

  const describe = () => {
    const el = sr.current;
    const { row, col } = st.current;
    const h = latest.current;
    if (!el) return;
    const v = h.z[row]?.[col];
    el.textContent = `${h.y[row] ?? ""} ${h.xlabel} ${h.x[col] ?? ""} ${v == null ? "no value" : heatText(v, h.unit)}`;
  };

  const draw = () => {
    const el = box.current;
    const cv = canvas.current;
    if (!el || !cv) return;
    const w = el.clientWidth;
    const hpx = el.clientHeight;
    if (w < 40 || hpx < 40) return;
    const dpr = window.devicePixelRatio || 1;
    cv.width = Math.round(w * dpr);
    cv.height = Math.round(hpx * dpr);
    cv.style.width = `${w}px`;
    cv.style.height = `${hpx}px`;
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const c = readColors(el);
    const h = latest.current;
    ctx.fillStyle = c.bg;
    ctx.fillRect(0, 0, w, hpx);
    ctx.font = c.font;
    ctx.textBaseline = "middle";
    const range = heatRange(h.z);
    const cols = h.x.length;
    const cw = Math.max(24, (w - LABEL_W) / Math.max(1, cols));
    ctx.fillStyle = c.dim;
    ctx.textAlign = "center";
    h.x.forEach((x, j) => ctx.fillText(String(x), LABEL_W + j * cw + cw / 2, HEAD_H / 2));
    ctx.textAlign = "left";
    ctx.fillText(h.ylabel, 4, HEAD_H / 2);
    const { row, col } = st.current;
    h.y.forEach((label, i) => {
      const y = HEAD_H + i * CELL_H;
      if (y + CELL_H > hpx) return;
      ctx.fillStyle = i === row ? c.fg : c.dim;
      ctx.textAlign = "left";
      ctx.fillText(label, 4, y + CELL_H / 2);
      h.z[i]?.forEach((v, j) => {
        const x = LABEL_W + j * cw;
        if (v != null && Number.isFinite(v) && range) {
          ctx.globalAlpha = heatLevel(v, range[0], range[1]);
          ctx.fillStyle = c.hue;
          ctx.fillRect(x + 1, y + 1, cw - 2, CELL_H - 2);
          ctx.globalAlpha = 1;
        }
        ctx.fillStyle = v != null && range && heatLevel(v, range[0], range[1]) > 0.55 ? c.bg : c.fg;
        ctx.textAlign = "center";
        ctx.fillText(heatText(v, h.unit), x + cw / 2, y + CELL_H / 2);
        if (i === row && j === col) {
          ctx.strokeStyle = c.fg;
          ctx.lineWidth = 1;
          ctx.strokeRect(x + 0.5, y + 0.5, cw - 1, CELL_H - 1);
        }
      });
    });
    if (range) {
      ctx.fillStyle = c.dim;
      ctx.textAlign = "right";
      ctx.fillText(`${heatText(range[0], h.unit)} - ${heatText(range[1], h.unit)} (${h.unit === "pct" ? "%" : h.unit})`, w - 4, HEAD_H / 2);
    }
  };

  useImperativeHandle(ref, () => ({
    move(dRow, dCol) {
      const h = latest.current;
      const s = st.current;
      s.row = Math.min(Math.max(0, s.row + dRow), Math.max(0, h.y.length - 1));
      s.col = Math.min(Math.max(0, s.col + dCol), Math.max(0, h.x.length - 1));
      draw();
      describe();
    },
  }));

  useEffect(() => {
    const s = st.current;
    s.row = Math.min(s.row, Math.max(0, heat.y.length - 1));
    s.col = Math.min(s.col, Math.max(0, heat.x.length - 1));
    draw();
    describe();
  }, [heat]);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(() => draw());
    ro.observe(el);
    const off = displayVersion.subscribe(() => draw());
    return () => {
      ro.disconnect();
      off();
    };
  }, []);

  return (
    <div ref={box} className="heatmap" data-testid={`heat-${heat.id}`}>
      <canvas ref={canvas} />
      <div ref={sr} className="sr" data-testid="heat-sr" />
    </div>
  );
}

export const HeatMap = forwardRef(HeatMapInner);
