/**
 * BT RUNS (Phase 12): the stored runs (last 200) as a grid. J/K move, Enter opens a run in this panel (`BT OPEN id`),
 * C marks a run (two marks open the comparison: metric differences B minus A as the server computed them, V switches to
 * the two equity lines), Backspace or Q leaves the comparison, E exports the visible table. Nothing is invented: an
 * empty list or a failed request says so.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { fmtMetric, METRIC_ROWS, type MetricRow } from "../bt/metricsFormat";
import { ChartView, type BarData, type ChartHandle } from "../chart/ChartView";
import { Grid, type CellColor, type Column, type GridHandle } from "../components/Grid";
import { PanelNote } from "../components/PanelNote";
import { fmtAge } from "../format";
import { registerPanelKeys } from "../keys/panelKeys";
import { ApiError, btApi, type BtCompare, type BtRunCard } from "../net/api";
import { replaceView } from "../state/workspace";
import { navKey, useLatest } from "./quoteRows";
import { gridCsv, useCsvExport, type CsvTable } from "./tableExport";

const signColor = (v: number | null | undefined): CellColor => (v == null || v === 0 ? "fg" : v > 0 ? "up" : "down");
const NO_INDICATORS: never[] = [];
const errText = (e: unknown) => {
  const a = e as ApiError;
  return `${a.message ?? String(e)}${a.detail ? ` (${a.detail})` : ""}`;
};
const label = (r: BtRunCard) => r.rule ?? (r.strategy ? `STRATEGY ${r.strategy}` : "PYTHON STRATEGY");

interface Row extends BtRunCard {
  marked: string;
}

const COLS: Column<Row>[] = [
  { title: "", width: 2, text: (r) => r.marked, color: () => "acc" },
  { title: "RUN", width: 17, text: (r) => r.id, color: () => "dim" },
  { title: "RULE", width: 30, text: (r) => label(r) },
  { title: "SYMBOLS", width: 14, text: (r) => r.symbols.join(","), color: () => "acc" },
  { title: "PERIOD", width: 9, text: (r) => `${r.interval} ${r.range}` },
  { title: "ENGINE", width: 10, text: (r) => (r.engine ?? r.labels?.engine ?? "").toUpperCase(), color: () => "dim" },
  { title: "TOTAL", width: 10, align: "right", text: (r) => fmtMetric("total_return", r.metrics.total_return), color: (r) => signColor(r.metrics.total_return) },
  { title: "SHARPE", width: 8, align: "right", text: (r) => fmtMetric("sharpe", r.metrics.sharpe) },
  { title: "MAX DD", width: 9, align: "right", text: (r) => fmtMetric("max_drawdown", r.metrics.max_drawdown), color: (r) => signColor(r.metrics.max_drawdown) },
  { title: "TRADES", width: 7, align: "right", text: (r) => fmtMetric("trade_count", r.metrics.trade_count) },
  { title: "AGE", width: 8, align: "right", text: (r) => fmtAge(Date.now() / 1000 - r.created_at), color: () => "dim" },
];

interface DiffLine {
  row: MetricRow;
  a: number | null | undefined;
  b: number | null | undefined;
  d: number | null | undefined;
}
const DIFF_COLS: Column<DiffLine>[] = [
  { title: "METRIC", width: 26, text: (m) => m.row.label, color: () => "dim" },
  { title: "A", width: 14, align: "right", text: (m) => fmtMetric(m.row.key, m.a) },
  { title: "B", width: 14, align: "right", text: (m) => fmtMetric(m.row.key, m.b) },
  { title: "B - A", width: 14, align: "right", text: (m) => fmtMetric(m.row.key, m.d), color: (m) => (m.row.signed ? signColor(m.d) : "fg") },
];

function line(points: [number, number][], symbol: string): BarData {
  const t = Float64Array.from(points, (p) => p[0]);
  const c = Float64Array.from(points, (p) => p[1]);
  return { symbol, interval: "1d", tz: "UTC", t, o: c, h: c, l: c, c, v: new Float64Array(t.length) };
}

export default function BtRuns({ panelId }: { panelId: number }) {
  const [runs, setRuns] = useState<BtRunCard[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [marks, setMarks] = useState<string[]>([]);
  const [cmp, setCmp] = useState<BtCompare | null>(null);
  const [view, setView] = useState<"METRICS" | "CHART">("METRICS");
  const [msg, setMsg] = useState<string | null>(null);
  const grid = useRef<GridHandle>(null);
  const chart = useRef<ChartHandle>(null);

  useEffect(() => {
    let live = true;
    btApi
      .runs()
      .then((r) => live && setRuns(r.runs))
      .catch((e) => live && setError(errText(e)));
    return () => {
      live = false;
    };
  }, []);

  const rows = useMemo<Row[]>(() => (runs ?? []).map((r) => ({ ...r, marked: marks.includes(r.id) ? (marks[0] === r.id ? "A" : "B") : "" })), [runs, marks]);
  const diffRows = useMemo<DiffLine[]>(
    () => (cmp ? METRIC_ROWS.map((row) => ({ row, a: cmp.a.metrics[row.key], b: cmp.b.metrics[row.key], d: cmp.diff[row.key] })) : []),
    [cmp],
  );
  const chartBits = useMemo(() => (cmp ? { data: line(cmp.a.equity, "A"), compare: { symbol: "B", t: Float64Array.from(cmp.b.equity, (p) => p[0]), c: Float64Array.from(cmp.b.equity, (p) => p[1]) } } : null), [cmp]);

  const latest = useLatest({ rows, marks, cmp, view, diffRows });

  const compare = (a: string, b: string) => {
    setMsg("COMPARING…");
    btApi
      .compare(a, b)
      .then((r) => {
        setCmp(r);
        setView("METRICS");
        setMsg(null);
      })
      .catch((e) => {
        setMarks([]);
        setMsg(`ERR: ${errText(e)}`);
      });
  };

  useEffect(() => {
    grid.current?.moveTo(0);
  }, [cmp === null, view]);

  useCsvExport(panelId, (): CsvTable | null => {
    const { rows: r, cmp: c, diffRows: d } = latest.current;
    if (c) return gridCsv("BT_COMPARE", DIFF_COLS, d);
    return gridCsv("BT_RUNS", COLS, r);
  });

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        if (e.ctrlKey || e.altKey || e.metaKey || e.key === "Shift" || e.key === "Control" || e.key === "Alt" || e.key === "Meta") return false;
        const { rows: r, marks: m, cmp: c, view: v, diffRows: d } = latest.current;
        const k = e.key.toLowerCase();
        if (c) {
          if (k === "backspace" || k === "q") {
            setCmp(null);
            setMarks([]);
            return true;
          }
          if (k === "v") {
            setView(v === "METRICS" ? "CHART" : "METRICS");
            return true;
          }
          if (v === "METRICS") return navKey(e, grid.current, d.length);
          const ch = chart.current;
          if (e.key === "h" || e.key === "ArrowLeft") return ch?.pan(-10), true;
          if (e.key === "l" || e.key === "ArrowRight") return ch?.pan(10), true;
          if (e.key === "+" || e.key === "=") return ch?.zoom(0.8), true;
          if (e.key === "-") return ch?.zoom(1.25), true;
          return false;
        }
        if (navKey(e, grid.current, r.length)) return true;
        const row = r[grid.current?.selected() ?? 0];
        if (!row) return false;
        if (e.key === "Enter") {
          replaceView(panelId, (view) => ({ ...view, args: ["OPEN", row.id] }));
          return true;
        }
        if (k === "c") {
          if (m.includes(row.id)) {
            setMarks(m.filter((x) => x !== row.id));
            return true;
          }
          const next = [...m, row.id];
          setMarks(next);
          if (next.length === 2) compare(next[0], next[1]);
          else setMsg(`MARKED ${next.length}: C ON A SECOND RUN TO COMPARE`);
          return true;
        }
        return false;
      }),
    // everything is read through `latest`
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [panelId, latest],
  );

  if (error)
    return (
      <div className="fn bt">
        <PanelNote kind="error" hint="Press F5 or run BT RUNS again to retry.">ERR: {error}</PanelNote>
      </div>
    );
  if (!runs)
    return (
      <div className="fn bt">
        <PanelNote kind="loading">LOADING RUNS…</PanelNote>
      </div>
    );
  if (cmp) {
    const head = (r: BtRunCard, tag: string) => (
      <div className="line">
        <span className="acc">{tag}</span> {r.symbols.join(",")} · {label(r)} · {r.interval} {r.range} · {(r.engine ?? r.labels?.engine ?? "").toUpperCase()}
      </div>
    );
    return (
      <div className="fn">
        <div className="line">
          <span className="acc">BT COMPARE</span> <span className="dim">B - A · {cmp.a.labels?.headline}</span>
        </div>
        {head(cmp.a, "A")}
        {head(cmp.b, "B")}
        <div className="line">
          B - A{" "}
          {[["TOTAL RETURN", "total_return"], ["ANNUAL", "annual_return"], ["MAX DD", "max_drawdown"], ["SHARPE", "sharpe"], ["TRADES", "trade_count"]].map(([name, key]) => (
            <span key={key}>
              {" · "}
              {name} <span className={signColor(cmp.diff[key]) === "fg" ? "" : signColor(cmp.diff[key])}>{fmtMetric(key, cmp.diff[key])}</span>
            </span>
          ))}
        </div>
        <div className="line dim">
          VIEW <span className="bt-view acc">{view}</span> · V SWITCH (METRICS / EQUITY LINES) · BACKSPACE BACK · E EXPORT
        </div>
        {view === "METRICS" ? (
          <Grid ref={grid} columns={DIFF_COLS} rows={diffRows} />
        ) : (
          chartBits && <ChartView key={`${cmp.a.id}-${cmp.b.id}`} ref={chart} data={chartBits.data} compare={chartBits.compare} type="LINE" log={false} indicators={NO_INDICATORS} readoutLabel="A" />
        )}
        {msg && <div className="dim">{msg}</div>}
      </div>
    );
  }
  return (
    <div className="fn">
      <div className="line">
        <span className="acc">BT RUNS</span> <span className="dim">{runs.length} STORED (LAST 200) · J/K MOVE · ENTER OPEN · C MARK TWO TO COMPARE · E EXPORT</span>
      </div>
      {msg && <div className="dim">{msg}</div>}
      {runs.length ? (
        <Grid ref={grid} columns={COLS} rows={rows} />
      ) : (
        <PanelNote kind="empty" hint="Start one: BT AAPL SMA20>SMA50 1D 5Y (BT <SYMBOLS> <RULE> stores it here). In GUI mode type it in the command line at the top.">
          NO RUNS YET
        </PanelNote>
      )}
    </div>
  );
}
