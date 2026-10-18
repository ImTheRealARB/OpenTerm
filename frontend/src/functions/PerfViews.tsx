/**
 * Load-test views behind `PERF GRID <rows>` and `PERF CHART <bars>`. Generated locally and labelled
 * TEST DATA on screen; they exist so scripts/bench can measure scrolling and panning at scale.
 */
import { useEffect, useMemo, useRef } from "react";
import { ChartView, type BarData, type ChartHandle } from "../chart/ChartView";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { fmtBig, fmtPct, fmtPrice } from "../format";
import { registerPanelKeys } from "../keys/panelKeys";
import { candlePatterns, smc } from "../chart/patterns";
import { gauges } from "../perf/metrics";
import { seasonality } from "./seasMath";
import { hitTest, type Drawing, type Geo } from "../chart/drawings";

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

/** `PERF CALC`: times the Phase 19 chart maths on generated bars (TEST DATA) and publishes gauges p19.patternsMs / p19.seasMs (p95 of 15 runs). */
export function CalcBench() {
  const res = useMemo(() => {
    const r = rng(7);
    const p95 = (a: number[]) => [...a].sort((x, y) => x - y)[Math.min(a.length - 1, Math.floor(a.length * 0.95))];
    const n = 5000;
    const o = new Float64Array(n), h = new Float64Array(n), l = new Float64Array(n), c = new Float64Array(n);
    let px = 100;
    for (let i = 0; i < n; i++) {
      o[i] = px;
      px *= 1 + (r() - 0.5) * 0.04;
      c[i] = px;
      h[i] = Math.max(o[i], c[i]) * (1 + r() * 0.01);
      l[i] = Math.min(o[i], c[i]) * (1 - r() * 0.01);
    }
    const dn = 10000;
    const t = new Float64Array(dn), dc = new Float64Array(dn);
    let p = 100;
    for (let i = 0; i < dn; i++) {
      t[i] = 631152000 + i * 86400;
      p *= 1 + (r() - 0.5) * 0.02;
      dc[i] = p;
    }
    const pat: number[] = [];
    const seas: number[] = [];
    for (let k = 0; k < 15; k++) {
      let t0 = performance.now();
      candlePatterns(o, h, l, c);
      smc(o, h, l, c, 3);
      pat.push(performance.now() - t0);
      t0 = performance.now();
      seasonality(t, dc, "MONTH");
      seasonality(t, dc, "WOY");
      seasonality(t, dc, "DOM");
      seas.push(performance.now() - t0);
    }
    // 200 drawings (a third of each kind) hit-tested at points in the middle of the chart.
    const ds: Drawing[] = Array.from({ length: 200 }, (_, i) => {
      const t0 = 100 + (i % 50) * 10;
      const k = i % 3;
      return k === 0
        ? { id: `h${i}`, kind: "HLINE", pts: [{ t: t0, p: 50 + (i % 40) }] }
        : k === 1
          ? { id: `t${i}`, kind: "TREND", pts: [{ t: t0, p: 40 + (i % 30) }, { t: t0 + 200, p: 60 + (i % 20) }] }
          : { id: `f${i}`, kind: "FIB", pts: [{ t: t0, p: 40 }, { t: t0 + 300, p: 80 + (i % 10) }] };
    });
    const geo: Geo = { toX: (t) => t, toY: (p) => 1000 - p, width: 1200 };
    const hit: number[] = [];
    for (let k = 0; k < 15; k++) {
      const t0 = performance.now();
      for (let j = 0; j < 20; j++) hitTest(ds, 300 + j * 7, 930 + (j % 5), geo, 6);
      hit.push((performance.now() - t0) / 20);
    }
    gauges.set("p19.hitMs", p95(hit));
    gauges.set("p19.patternsMs", p95(pat));
    gauges.set("p19.seasMs", p95(seas));
    return { pat: p95(pat), seas: p95(seas), hit: p95(hit), n, dn };
  }, []);
  return (
    <div>
      <h2>PERF CALC (TEST DATA, NOT A SECURITY)</h2>
      <div>PATTERNS + SMC, {res.n} BARS: {res.pat.toFixed(2)} MS P95</div>
      <div>SEAS MONTH + WOY + DOM, {res.dn} DAILY BARS: {res.seas.toFixed(2)} MS P95</div>
      <div>HIT TEST OVER 200 DRAWINGS: {res.hit.toFixed(3)} MS P95</div>
    </div>
  );
}
