/**
 * Load-test views behind `PERF GRID <rows>` and `PERF CHART <bars>`. Generated locally and labelled
 * TEST DATA on screen; they exist so scripts/bench can measure scrolling and panning at scale.
 */
import { useEffect, useMemo, useRef } from "react";
import { ChartView, type BarData, type ChartHandle } from "../chart/ChartView";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { fmtBig, fmtPct, fmtPrice } from "../format";
import { registerPanelKeys } from "../keys/panelKeys";

function rng(seed: number) {
  return () => {
    seed = (seed * 1664525 + 1013904223) >>> 0;
    return seed / 2 ** 32;
  };
}

interface TRow {
  sym: string;
  px: number;
  pct: number;
  vol: number;
}

const COLS: Column<TRow>[] = [
  { title: "TEST ROW", width: 10, text: (r) => r.sym, color: () => "warn" },
  { title: "LAST", width: 10, align: "right", text: (r) => fmtPrice(r.px) },
  { title: "%CHG", width: 8, align: "right", text: (r) => fmtPct(r.pct), color: (r) => (r.pct >= 0 ? "up" : "down") },
  { title: "VOLUME", width: 9, align: "right", text: (r) => fmtBig(r.vol) },
  { title: "NOTE", width: 24, text: () => "TEST DATA, NOT A SECURITY", color: () => "dim" },
];

export function TestGrid({ panelId, rows }: { panelId: number; rows: number }) {
  const data = useMemo(() => {
    const r = rng(42);
    return Array.from({ length: rows }, (_, i) => ({ sym: `T${String(i).padStart(6, "0")}`, px: 10 + r() * 990, pct: (r() - 0.5) * 10, vol: r() * 1e7 }));
  }, [rows]);
  const grid = useRef<GridHandle>(null);
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const g = grid.current;
        if (!g) return false;
        if (e.key === "j" || e.key === "ArrowDown") g.move(1);
        else if (e.key === "k" || e.key === "ArrowUp") g.move(-1);
        else if (e.key === "PageDown") g.page(1);
        else if (e.key === "PageUp") g.page(-1);
        else if (e.key === "g") g.moveTo(0);
        else if (e.key === "G") g.moveTo(rows - 1);
        else return false;
        return true;
      }),
    [panelId, rows],
  );
  return (
    <div className="fn">
      <div className="line warn">PERF GRID: {rows.toLocaleString("en-US")} ROWS OF GENERATED TEST DATA · J/K PGUP/PGDN G/G</div>
      <Grid ref={grid} columns={COLS} rows={data} />
    </div>
  );
}

export function TestChart({ panelId, bars }: { panelId: number; bars: number }) {
  const data = useMemo<BarData>(() => {
    const r = rng(7);
    const t = new Float64Array(bars), o = new Float64Array(bars), h = new Float64Array(bars), l = new Float64Array(bars), c = new Float64Array(bars), v = new Float64Array(bars);
    let px = 100;
    const t0 = 1_500_000_000;
    for (let i = 0; i < bars; i++) {
      const op = px;
      px = Math.max(1, px * (1 + (r() - 0.5) * 0.02));
      t[i] = t0 + i * 3600;
      o[i] = op;
      c[i] = px;
      h[i] = Math.max(op, px) * (1 + r() * 0.005);
      l[i] = Math.min(op, px) * (1 - r() * 0.005);
      v[i] = r() * 1e6;
    }
    return { symbol: "TEST", interval: "60m", tz: "UTC", t, o, h, l, c, v };
  }, [bars]);
  const chart = useRef<ChartHandle>(null);
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const ch = chart.current;
        if (!ch) return false;
        if (e.key === "ArrowLeft") ch.pan(-10);
        else if (e.key === "ArrowRight") ch.pan(10);
        else if (e.key === "+" || e.key === "=") ch.zoom(0.8);
        else if (e.key === "-") ch.zoom(1.25);
        else return false;
        return true;
      }),
    [panelId],
  );
  const indicators = useMemo(() => [] as never[], []);
  return (
    <div className="fn">
      <div className="line warn">PERF CHART: {bars.toLocaleString("en-US")} BARS OF GENERATED TEST DATA · ←/→ PAN · +/- ZOOM</div>
      <ChartView ref={chart} data={data} type="CANDLE" log={false} indicators={indicators} />
    </div>
  );
}
