/**
 * The BETA scatter: one dot per period (x = the benchmark's return, y = the security's return, both in percent) and the fitted
 * line y = alpha + beta x. Drawn by hand on a <canvas> (no chart library: lightweight-charts has no numeric x axis).
 * Colours come from the theme's CSS variables and the font from `--font`, so every theme and font setting applies; it is redrawn
 * only when the data, the size or the theme changes, never per frame.
 */
import { useCallback, useEffect, useRef } from "react";
import { niceTicks, tickLabel } from "../research/chartMath";
import { displayVersion } from "../settings/runtime";
import { fitLine, scatterBox } from "./traBeta";

// Space left round the plot for the tick labels (px).
const PAD_L = 44;
const PAD_R = 10;
const PAD_T = 14;
const PAD_B = 24;

export interface ScatterProps {
  x: number[];
  y: number[];
  beta: number;
  /** Intercept per period, in percent (the same unit as the points). */
  alphaPct: number;
  xLabel: string;
  yLabel: string;
}

export function BetaScatter(props: ScatterProps) {
  const box = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  // `draw` is called from observers set up once; it reads the newest props through this ref so it never draws stale data.
  const latest = useRef(props);
  latest.current = props;

  // useCallback with no deps: the function reads only refs, so it is the same function every render and the observers below can use it safely.
  const draw = useCallback(() => {
    const el = box.current;
    const cv = canvas.current;
    if (!el || !cv) return;
    const w = el.clientWidth;
    const h = el.clientHeight;
    if (w < 40 || h < 40) return;
    // Scale the bitmap by the device pixel ratio so the lines stay sharp on a high-density screen.
    const dpr = window.devicePixelRatio || 1;
    cv.width = Math.round(w * dpr);
    cv.height = Math.round(h * dpr);
    cv.style.width = `${w}px`;
    cv.style.height = `${h}px`;
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const cs = getComputedStyle(el);
    const v = (n: string) => cs.getPropertyValue(n).trim();
    const col = { bg: v("--bg"), fg: v("--fg"), dim: v("--fg-dim"), grid: v("--chart-grid") || v("--line"), acc: v("--accent") };
    ctx.fillStyle = col.bg;
    ctx.fillRect(0, 0, w, h);
    ctx.font = `${v("--fs") || "12px"} ${v("--font")}`;
    ctx.textBaseline = "middle";

    const { x, y, beta, alphaPct, xLabel, yLabel } = latest.current;
    const b = scatterBox(x, y);
    if (!b) {
      ctx.fillStyle = col.dim;
      ctx.fillText("NO POINTS TO DRAW", PAD_L, h / 2);
      return;
    }
    const pw = w - PAD_L - PAD_R;
    const ph = h - PAD_T - PAD_B;
    const X = (vx: number) => PAD_L + ((vx - b.xMin) / (b.xMax - b.xMin)) * pw;
    const Y = (vy: number) => PAD_T + (1 - (vy - b.yMin) / (b.yMax - b.yMin)) * ph;

    // Grid lines and tick labels. The 0.5 offset puts a 1 px line on a pixel row instead of blurring it over two.
    ctx.lineWidth = 1;
    ctx.strokeStyle = col.grid;
    ctx.fillStyle = col.dim;
    ctx.textAlign = "right";
    for (const t of niceTicks(b.yMin, b.yMax, 5)) {
      const py = Math.round(Y(t)) + 0.5;
      ctx.beginPath();
      ctx.moveTo(PAD_L, py);
      ctx.lineTo(w - PAD_R, py);
      ctx.stroke();
      ctx.fillText(tickLabel(t), PAD_L - 5, py);
    }
    ctx.textAlign = "center";
    for (const t of niceTicks(b.xMin, b.xMax, Math.max(2, Math.floor(pw / 80)))) {
      const px = Math.round(X(t)) + 0.5;
      ctx.beginPath();
      ctx.moveTo(px, PAD_T);
      ctx.lineTo(px, PAD_T + ph);
      ctx.stroke();
      ctx.fillText(tickLabel(t), px, h - PAD_B / 2 + 2);
    }
    // The two zero axes, in a stronger colour: they are where "no move" sits.
    ctx.strokeStyle = col.dim;
    ctx.beginPath();
    ctx.moveTo(PAD_L, Math.round(Y(0)) + 0.5);
    ctx.lineTo(w - PAD_R, Math.round(Y(0)) + 0.5);
    ctx.moveTo(Math.round(X(0)) + 0.5, PAD_T);
    ctx.lineTo(Math.round(X(0)) + 0.5, PAD_T + ph);
    ctx.stroke();

    // The dots: 2 x 2 px squares are the cheapest thing to draw (thousands of daily returns).
    ctx.fillStyle = col.fg;
    for (let i = 0; i < x.length; i++) {
      if (Number.isFinite(x[i]) && Number.isFinite(y[i])) ctx.fillRect(X(x[i]) - 1, Y(y[i]) - 1, 2, 2);
    }
    // The fitted line, clipped to the plot so a steep beta does not draw over the labels.
    const [p0, p1] = fitLine(b, alphaPct, beta);
    ctx.save();
    ctx.beginPath();
    ctx.rect(PAD_L, PAD_T, pw, ph);
    ctx.clip();
    ctx.strokeStyle = col.acc;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(X(p0[0]), Y(p0[1]));
    ctx.lineTo(X(p1[0]), Y(p1[1]));
    ctx.stroke();
    ctx.restore();

    ctx.fillStyle = col.dim;
    ctx.textAlign = "left";
    ctx.fillText(yLabel, 4, 6);
    ctx.textAlign = "right";
    ctx.fillText(xLabel, w - PAD_R, h - 5);
  }, []);

  // No deps array on purpose: redraw after every render, because the new props arrive through `latest`.
  useEffect(() => {
    draw();
  });

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(() => draw());
    ro.observe(el);
    const off = displayVersion.subscribe(() => draw()); // a theme or font change repaints
    return () => {
      ro.disconnect();
      off();
    };
  }, [draw]);

  return (
    <div ref={box} className="tb-scatter" data-testid="beta-scatter">
      <canvas ref={canvas} />
      {/* Screen readers cannot see the canvas: say what it shows. */}
      <div className="sr">
        {props.x.length} POINTS, FITTED LINE BETA {props.beta.toFixed(2)}, ALPHA {props.alphaPct.toFixed(3)}% PER PERIOD
      </div>
    </div>
  );
}
