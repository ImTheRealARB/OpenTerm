/**
 * Numeric-axis line chart on a canvas (Phase 14: smile, payoff, term structure, COT history, curves). lightweight-charts has no numeric
 * x axis, and these series are not time series. Drawn once per data change or theme change; no animation, no shadows.
 */
import { useEffect, useRef } from "react";
import { displayVersion } from "../settings/runtime";
import "./dataColors.css";
import { extentOf, niceTicks, runs, tickLabel, type ChartPayload } from "../research/chartMath";

const PAD_L = 52;
const PAD_R = 12;
const PAD_T = 16;
const PAD_B = 26;

interface Colors {
  bg: string;
  fg: string;
  dim: string;
  line: string;
  grid: string;
  series: string[];
  font: string;
}

function readColors(el: Element): Colors {
  const cs = getComputedStyle(el);
  const v = (n: string) => cs.getPropertyValue(n).trim();
  return {
    bg: v("--bg"), fg: v("--fg"), dim: v("--fg-dim"), line: v("--line"), grid: v("--chart-grid") || v("--line"),
    series: [v("--accent"), v("--fg"), v("--up"), v("--warn"), v("--down"), v("--fg-dim")],
    font: `${v("--fs") || "12px"} ${v("--font")}`,
  };
}

export function XYChart({ chart }: { chart: ChartPayload }) {
  const box = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const latest = useRef(chart);
  latest.current = chart;

  const draw = () => {
    const el = box.current;
    const cv = canvas.current;
    if (!el || !cv) return;
    const w = el.clientWidth;
    const h = el.clientHeight;
    if (w < 20 || h < 20) return;
    const dpr = window.devicePixelRatio || 1;
    cv.width = Math.round(w * dpr);
    cv.height = Math.round(h * dpr);
    cv.style.width = `${w}px`;
    cv.style.height = `${h}px`;
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const c = readColors(el);
    const { series, marks = [] } = latest.current;
    ctx.fillStyle = c.bg;
    ctx.fillRect(0, 0, w, h);
    ctx.font = c.font;
    ctx.textBaseline = "middle";
    const ext = extentOf(series);
    if (!ext) {
      ctx.fillStyle = c.dim;
      ctx.fillText("NO DRAWABLE POINTS", PAD_L, h / 2);
      return;
    }
    const pw = w - PAD_L - PAD_R;
    const ph = h - PAD_T - PAD_B;
    const X = (x: number) => PAD_L + ((x - ext.xMin) / (ext.xMax - ext.xMin)) * pw;
    const Y = (y: number) => PAD_T + (1 - (y - ext.yMin) / (ext.yMax - ext.yMin)) * ph;

    ctx.strokeStyle = c.grid;
    ctx.lineWidth = 1;
    ctx.fillStyle = c.dim;
    ctx.textAlign = "right";
    for (const t of niceTicks(ext.yMin, ext.yMax, 5)) {
      const y = Math.round(Y(t)) + 0.5;
      ctx.beginPath();
      ctx.moveTo(PAD_L, y);
      ctx.lineTo(w - PAD_R, y);
      ctx.stroke();
      ctx.fillText(tickLabel(t), PAD_L - 6, y);
    }
    ctx.textAlign = "center";
    for (const t of niceTicks(ext.xMin, ext.xMax, Math.max(2, Math.floor(pw / 90)))) {
      const x = Math.round(X(t)) + 0.5;
      ctx.beginPath();
      ctx.moveTo(x, PAD_T);
      ctx.lineTo(x, PAD_T + ph);
      ctx.stroke();
      ctx.fillText(tickLabel(t), x, h - PAD_B / 2 + 2);
    }
    // zero line (payoff, net positions) in the foreground colour: it is the break-even
    if (ext.yMin < 0 && ext.yMax > 0) {
      ctx.strokeStyle = c.dim;
      ctx.beginPath();
      ctx.moveTo(PAD_L, Math.round(Y(0)) + 0.5);
      ctx.lineTo(w - PAD_R, Math.round(Y(0)) + 0.5);
      ctx.stroke();
    }
    for (const m of marks) {
      if (m.x < ext.xMin || m.x > ext.xMax) continue;
      const x = Math.round(X(m.x)) + 0.5;
      ctx.strokeStyle = c.dim;
      ctx.setLineDash([2, 3]);
      ctx.beginPath();
      ctx.moveTo(x, PAD_T);
      ctx.lineTo(x, PAD_T + ph);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = c.fg;
      ctx.textAlign = "left";
      ctx.fillText(m.label, x + 3, PAD_T + 6);
    }
    ctx.lineWidth = 1.5;
    series.forEach((s, i) => {
      ctx.strokeStyle = c.series[i % c.series.length];
      ctx.setLineDash(s.dash ? [5, 4] : []);
      for (const run of runs(s.points)) {
        ctx.beginPath();
        run.forEach(([x, y], k) => (k ? ctx.lineTo(X(x), Y(y)) : ctx.moveTo(X(x), Y(y))));
        ctx.stroke();
        if (run.length === 1) ctx.fillRect(X(run[0][0]) - 2, Y(run[0][1]) - 2, 4, 4);
      }
    });
    ctx.setLineDash([]);
    ctx.textAlign = "left";
    ctx.fillStyle = c.dim;
    ctx.fillText(latest.current.ylabel, 4, 8);
    ctx.textAlign = "right";
    ctx.fillText(latest.current.xlabel, w - PAD_R, h - 6);
    // legend (names only when there is more than one series)
    if (series.length > 1) {
      let lx = PAD_L + 6;
      series.forEach((s, i) => {
        ctx.fillStyle = c.series[i % c.series.length];
        ctx.textAlign = "left";
        ctx.fillRect(lx, 7, 8, 2);
        ctx.fillText(s.name, lx + 12, 8);
        lx += 18 + s.name.length * 7;
      });
    }
  };

  useEffect(() => {
    draw();
  }, [chart]);

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
    <div ref={box} className="xychart" data-testid={`chart-${chart.id}`}>
      <canvas ref={canvas} />
      <div className="sr" data-testid="chart-sr">
        {chart.title}: {chart.series.map((s) => `${s.name} ${s.points.filter((p) => p[1] != null).length} points`).join(", ")}
      </div>
    </div>
  );
}
