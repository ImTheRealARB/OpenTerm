/**
 * BT (Phase 12): backtest a rule on historical bars. `BT AAPL SMA20>SMA50 1D 5Y [SHORT] [FEES=bps] [SLIP=bps] ...`
 * The rule is checked here first (bt/ruleParse.ts mirrors the backend parser), then POST /api/bt/run starts a job;
 * `J` frames drive the progress line and the finished run is fetched by id. Every result carries the labels of
 * spec decision L (historical simulation, data sources and age, ADJ/RAW, fees, slippage, engine, warm-up).
 * V / Shift+V cycle CHART / METRICS / TRADES / CODE (1-4 pick one; Tab stays the global next-panel key). Nothing is invented: failures show the backend's error.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { fmtMetric, METRIC_ROWS, type MetricRow } from "../bt/metricsFormat";
import { BT_USAGE, isBtRun, parseBtArgs, type BtRun } from "../bt/ruleParse";
import { ChartView, type BarData, type ChartHandle } from "../chart/ChartView";
import { Grid, type CellColor, type Column, type GridHandle } from "../components/Grid";
import { fmtAge, fmtNum, fmtPct, fmtPrice } from "../format";
import { registerPanelKeys } from "../keys/panelKeys";
import { ApiError, btApi, type BtRunFull, type BtTrade } from "../net/api";
import { isActive, progressText } from "../net/jobFrames";
import { adoptJob, cancelJob, fetchJob, useJob } from "../net/jobs";
import { afterPaint, commandStartedAt, gauges, series } from "../perf/metrics";
import { navKey, useLatest } from "./quoteRows";
import type { FunctionProps } from "./registry";
import { gridCsv, useCsvExport, type CsvTable } from "./tableExport";

const VIEWS = ["CHART", "METRICS", "TRADES", "CODE"] as const;
type View = (typeof VIEWS)[number];
/** Keys that belong to later Phase 12 steps: say so instead of doing nothing. */
const LATER: Record<string, string> = {
  m: "M: MONTE CARLO ARRIVES IN PHASE 12 STEP 6",
  w: "W: WALK-FORWARD ARRIVES IN PHASE 12 STEP 6",
  s: "S: SAVING STRATEGIES ARRIVES WITH THE STRATEGY EDITOR (PHASE 12 STEP 4B)",
};
const SUB_STEP: Record<string, string> = { RUNS: "7", EXPORT: "7", MC: "6", WF: "6", SAVE: "4B", LOAD: "4B", DEL: "4B" };

type State =
  | { k: "usage" }
  | { k: "bad"; error: string; rule?: string; col?: number }
  | { k: "later"; text: string }
  | { k: "submitting" }
  | { k: "running"; jobId: string }
  | { k: "loading"; runId: string }
  | { k: "done"; run: BtRunFull }
  | { k: "failed"; error: string };

const errText = (e: unknown) => {
  const a = e as ApiError;
  return `${a.message ?? String(e)}${a.detail ? ` (${a.detail})` : ""}`;
};

interface MetricLine {
  row: MetricRow;
  v: number | null | undefined;
}
const signColor = (v: number | null | undefined): CellColor => (v == null || v === 0 ? "fg" : v > 0 ? "up" : "down");
const METRIC_COLS: Column<MetricLine>[] = [
  { title: "METRIC", width: 26, text: (m) => m.row.label, color: () => "dim" },
  { title: "VALUE", width: 14, align: "right", text: (m) => fmtMetric(m.row.key, m.v), color: (m) => (m.row.signed ? signColor(m.v) : "fg") },
];

const TRADE_COLS: Column<BtTrade>[] = [
  { title: "SYMBOL", width: 10, text: (t) => t.symbol, color: () => "acc" },
  { title: "SIDE", width: 6, text: (t) => (t.direction > 0 ? "LONG" : "SHORT"), color: (t) => (t.direction > 0 ? "up" : "down") },
  { title: "ENTRY", width: 11, text: (t) => t.entry_time },
  { title: "EXIT", width: 11, text: (t) => t.exit_time },
  { title: "ENTRY PX", width: 11, align: "right", text: (t) => fmtPrice(t.entry_price) },
  { title: "EXIT PX", width: 11, align: "right", text: (t) => fmtPrice(t.exit_price) },
  { title: "SIZE", width: 11, align: "right", text: (t) => fmtNum(t.size, 2) },
  { title: "P&L", width: 12, align: "right", text: (t) => fmtPrice(t.pnl), color: (t) => signColor(t.pnl) },
  { title: "P&L %", width: 9, align: "right", text: (t) => (t.pnl_pct == null ? "—" : fmtPct(t.pnl_pct * 100)), color: (t) => signColor(t.pnl_pct) },
  { title: "FEES", width: 9, align: "right", text: (t) => fmtPrice(t.commission), color: () => "dim" },
  { title: "BARS", width: 6, align: "right", text: (t) => fmtNum(t.holding_bars, 0), color: () => "dim" },
  { title: "EXIT REASON", width: 14, text: (t) => (t.exit_reason ?? "").toUpperCase(), color: () => "dim" },
];

function request(a: BtRun) {
  return {
    rule: a.rule, symbols: a.symbols, interval: a.interval, range: a.range,
    options: {
      ...(a.short ? { short: true } : {}), ...(a.fees !== undefined ? { fees_bps: a.fees } : {}),
      ...(a.slip !== undefined ? { slip_bps: a.slip } : {}), ...(a.cash !== 100_000 ? { cash: a.cash } : {}),
      ...(a.bench ? { bench: a.bench } : {}), ...(a.mkt ? { engine: a.mkt } : {}),
    },
  };
}

/** Equity as a single-value BarData (FRED-style line), benchmark as the compare line, drawdown % for pane 2. */
function chartData(run: BtRunFull) {
  const n = run.equity.length;
  const t = new Float64Array(n);
  const c = new Float64Array(n);
  const dd = new Float64Array(n);
  let peak = -Infinity;
  for (let i = 0; i < n; i++) {
    t[i] = run.equity[i][0];
    c[i] = run.equity[i][1];
    peak = Math.max(peak, c[i]);
    dd[i] = peak > 0 ? (c[i] / peak - 1) * 100 : NaN;
  }
  const data: BarData = { symbol: "EQUITY", interval: run.interval === "1W" ? "1wk" : "1d", tz: "UTC", t, o: c, h: c, l: c, c, v: new Float64Array(n) };
  const bn = run.benchmark.length;
  const compare = bn
    ? { symbol: "BENCH", t: Float64Array.from(run.benchmark, (p) => p[0]), c: Float64Array.from(run.benchmark, (p) => p[1]) }
    : null;
  return { data, compare, drawdown: { title: "DRAWDOWN", v: dd } };
}

export default function BT({ panelId, args }: FunctionProps) {
  const parsed = useMemo(() => parseBtArgs(args), [args]);
  const [state, setState] = useState<State>({ k: "usage" });
  const [view, setView] = useState<View>("CHART");
  const [msg, setMsg] = useState<string | null>(null);
  const grid = useRef<GridHandle>(null);
  const chart = useRef<ChartHandle>(null);
  const t0 = useRef<number | null>(null);
  const jobId = state.k === "running" ? state.jobId : null;
  const job = useJob(jobId);

  const load = (runId: string) => {
    setState({ k: "loading", runId });
    const t = performance.now();
    btApi
      .get(runId)
      .then((run) => {
        gauges.set("bt.getMs", performance.now() - t);
        setState((s) => (s.k === "loading" && s.runId === runId ? { k: "done", run } : s));
      })
      .catch((e) => setState({ k: "failed", error: errText(e) }));
  };

  const submit = (a: BtRun) => {
    setState({ k: "submitting" });
    setMsg(null);
    const t = performance.now();
    btApi
      .run(request(a))
      .then((j) => {
        gauges.set("bt.postMs", performance.now() - t);
        const rec = adoptJob(j);
        // Cached: the answer carries the run (or at least its id). Otherwise the job effect below takes over,
        // also when a J frame finished the job before this answer arrived.
        if (rec.state === "done" && j.run && j.run_id && j.run.id === j.run_id) setState({ k: "done", run: j.run });
        else if (rec.state === "done" && j.run_id) load(j.run_id);
        else setState({ k: "running", jobId: rec.id });
      })
      .catch((e: ApiError) =>
        setState(e.col != null && e.col >= 0 ? { k: "bad", error: e.message, rule: a.rule, col: e.col } : { k: "failed", error: errText(e) }),
      );
  };

  // The command's arguments: validate locally, then submit. A remount (maximize, layout load) re-submits; the
  // backend answers an identical request from its cache at once.
  useEffect(() => {
    const started = commandStartedAt(panelId);
    t0.current = started !== undefined && performance.now() - started < 2000 ? started : null;
    if (!args.length) return setState({ k: "usage" });
    if (!parsed.ok) return setState({ k: "bad", error: parsed.error, rule: parsed.rule, col: parsed.col });
    if (!isBtRun(parsed)) return setState({ k: "later", text: `BT ${parsed.sub}: NOT BUILT YET (PHASE 12 STEP ${SUB_STEP[parsed.sub] ?? "?"})` });
    submit(parsed);
    // args identity changes only when the command changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [parsed]);

  // Job finished: fetch the stored run (the done frame or GET /api/jobs/{id} carries its id).
  useEffect(() => {
    if (!job || state.k !== "running") return;
    if (job.state === "error") return setState({ k: "failed", error: job.error ?? job.msg ?? "THE JOB FAILED" });
    if (job.state === "cancelled") return setState({ k: "failed", error: "CANCELLED" });
    if (job.state !== "done") return;
    const fromResult = (r: unknown) => (r && typeof r === "object" ? (r as { run_id?: string }).run_id : undefined);
    const id = fromResult(job.result);
    if (id) load(id);
    else
      fetchJob(job.id)
        .then((full) => {
          const rid = fromResult(full.result);
          if (rid) load(rid);
          else setState({ k: "failed", error: "THE JOB FINISHED WITHOUT A RUN ID" });
        })
        .catch((e) => setState({ k: "failed", error: errText(e) }));
    // reacts to the job record only
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job]);

  const run = state.k === "done" ? state.run : null;

  // Perf: command submit to the painted result (bench "BT result open to first paint").
  useEffect(() => {
    if (!run || t0.current === null) return;
    const start = t0.current;
    const rendered = performance.now();
    t0.current = null;
    afterPaint(() => {
      series.btOpen.push(performance.now() - start);
      gauges.set("bt.renderMs", performance.now() - rendered);
    });
  }, [run]);

  const metricRows = useMemo<MetricLine[]>(() => (run ? METRIC_ROWS.map((row) => ({ row, v: run.metrics[row.key] })) : []), [run]);
  const trades = run?.trades ?? [];
  const chartBits = useMemo(() => (run ? chartData(run) : null), [run]);
  useEffect(() => {
    if (view === "METRICS" || view === "TRADES") grid.current?.moveTo(0);
  }, [view, run]);

  const latest = useLatest({ state, view, run, metricRows, parsed, job });
  const name = run ? `BT_${run.symbols.slice(0, 3).join("-")}` : "BT";
  useCsvExport(panelId, (): CsvTable | null => {
    const { run: r, view: v, metricRows: m } = latest.current;
    if (!r) return null;
    if (v === "METRICS") return gridCsv(`${name}_METRICS`, METRIC_COLS, m, [{ title: "RAW", text: (x) => x.v ?? "" }]);
    if (v === "TRADES") return gridCsv(`${name}_TRADES`, TRADE_COLS, r.trades);
    const bench = new Map(r.benchmark.map(([t, b]) => [t, b]));
    return {
      name: `${name}_EQUITY`, header: ["DATE", "EQUITY", "BENCHMARK"],
      rows: r.equity.map(([t, e]) => [new Date(t * 1000).toISOString().slice(0, 10), e, bench.get(t) ?? ""]),
    };
  });

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        if (e.ctrlKey || e.altKey || e.metaKey) return false;
        if (e.key === "Shift" || e.key === "Control" || e.key === "Alt" || e.key === "Meta") return false;
        const { state: s, view: v, run: r, metricRows: m, parsed: p, job: j } = latest.current;
        // Tab is the global next-panel key and never reaches a panel: V / Shift+V cycle the views, 1-4 pick one.
        if ((e.key === "v" || e.key === "V") && r) {
          const i = VIEWS.indexOf(v);
          setView(VIEWS[(i + (e.key === "V" ? VIEWS.length - 1 : 1)) % VIEWS.length]);
          return true;
        }
        const d = Number(e.key);
        if (r && d >= 1 && d <= VIEWS.length) {
          setView(VIEWS[d - 1]);
          return true;
        }
        if ((v === "METRICS" || v === "TRADES") && r && navKey(e, grid.current, v === "METRICS" ? m.length : r.trades.length)) return true;
        if (v === "CHART" && r) {
          const c = chart.current;
          if (e.key === "h" || e.key === "ArrowLeft") return c?.pan(-10), true;
          if (e.key === "l" || e.key === "ArrowRight") return c?.pan(10), true;
          if (e.key === "+" || e.key === "=") return c?.zoom(0.8), true;
          if (e.key === "-") return c?.zoom(1.25), true;
        }
        const k = e.key.toLowerCase();
        if (k === "r" && isBtRun(p) && s.k !== "running" && s.k !== "submitting") {
          submit(p);
          return true;
        }
        if (k === "x" || (e.key === "Escape" && s.k === "running")) {
          if (s.k !== "running" || !j || !isActive(j.state)) return k === "x";
          setMsg(`CANCELLING ${j.id}…`);
          cancelJob(j.id).catch((err) => setMsg(`ERR: ${errText(err)}`));
          return true;
        }
        if (LATER[k] && r) {
          setMsg(LATER[k]);
          return true;
        }
        return false;
      }),
    // everything is read through `latest`
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [panelId, latest],
  );

  return (
    <div className="fn">
      <Head parsed={isBtRun(parsed) ? parsed : null} run={run} />
      {state.k === "usage" && (
        <>
          <div className="dim">{BT_USAGE}</div>
          <div className="dim">RULE TERMS: CLOSE OPEN HIGH LOW VOLUME SMAn EMAn RSIn HIGHn LOWn RETn NUMBER · OPS: &gt; &lt; &gt;= &lt;= CROSS&gt; CROSS&lt; · AND OR</div>
          <div className="dim">EXAMPLE: BT AAPL SMA20&gt;SMA50 1D 5Y · BT SPY,QQQ RSI14&lt;30 1D 10Y SHORT FEES=5 SLIP=5</div>
        </>
      )}
      {state.k === "bad" && <BadRule {...state} />}
      {state.k === "later" && <div className="warn">{state.text}</div>}
      {state.k === "submitting" && <div className="dim">FETCHING BARS AND SUBMITTING…</div>}
      {state.k === "running" && (
        <div className="line">
          <span className="acc">RUNNING </span>
          {progressText(job?.progress ?? 0)} <span className="dim">{job?.msg ?? job?.state.toUpperCase() ?? "QUEUED"} · X CANCEL</span>
        </div>
      )}
      {state.k === "loading" && <div className="dim">LOADING RUN {state.runId}…</div>}
      {state.k === "failed" && <div className="err">ERR: {state.error}</div>}
      {msg && <div className="dim">{msg}</div>}
      {run && (
        <>
          <Labels run={run} />
          <Headline run={run} />
          <div className="line">
            VIEW <span className="bt-view acc">{view}</span>
            <span className="dim"> · V NEXT VIEW (1-4: CHART METRICS TRADES CODE) · R RE-RUN · E EXPORT{view === "CHART" ? " · H/L PAN · +/- ZOOM" : " · J/K MOVE"}</span>
          </div>
          {view === "CHART" && chartBits && (
            <ChartView key={run.id} ref={chart} data={chartBits.data} compare={chartBits.compare} type="LINE" log={false} indicators={NO_INDICATORS} readoutLabel="EQUITY" lowerPane={chartBits.drawdown} />
          )}
          {view === "METRICS" && <Grid ref={grid} columns={METRIC_COLS} rows={metricRows} />}
          {view === "TRADES" && (trades.length ? <Grid ref={grid} columns={TRADE_COLS} rows={trades} /> : <div className="dim">NO TRADES IN THIS RUN</div>)}
          {view === "CODE" && <pre className="desc">{run.rule ?? run.code ?? (run.strategy ? `STRATEGY ${run.strategy}` : "—")}</pre>}
        </>
      )}
    </div>
  );
}

const NO_INDICATORS: never[] = [];

function Head({ parsed, run }: { parsed: BtRun | null; run: BtRunFull | null }) {
  const syms = run?.symbols ?? parsed?.symbols;
  if (!syms) return <div className="line"><span className="acc">BT</span> <span className="dim">BACKTEST</span></div>;
  const rule = run ? (run.rule ?? (run.strategy ? `STRATEGY ${run.strategy}` : "PYTHON STRATEGY")) : parsed?.rule;
  return (
    <div className="line">
      <span className="acc">BT</span> {syms.join(",")} · {rule} · {run?.interval ?? parsed?.interval} {run?.range ?? parsed?.range}
      {run?.engine && <span className="dim"> · ENGINE {run.engine.toUpperCase()}</span>}
    </div>
  );
}

function BadRule({ error, rule, col }: { error: string; rule?: string; col?: number }) {
  const hasCol = rule !== undefined && col !== undefined && col >= 0;
  return (
    <div>
      <div className="err">
        {hasCol ? "BAD RULE" : "BT"}: {error}
        {hasCol && ` AT COLUMN ${col + 1}`}
      </div>
      {hasCol && (
        <pre className="desc">
          {rule}
          {"\n"}
          <span className="err">{" ".repeat(col) + "^"}</span>
        </pre>
      )}
      {!hasCol && <div className="dim">{BT_USAGE}</div>}
    </div>
  );
}

function Labels({ run }: { run: BtRunFull }) {
  const l = run.labels;
  const sources = l.sources ?? [];
  return (
    <>
      <div className="line warn">
        {l.headline} · {l.prices} CLOSES · FEES {fmtNum(l.fees_bps, 0)} BPS · SLIP {fmtNum(l.slip_bps, 0)} BPS · WARM-UP {l.warmup_bars} BARS
        {l.short ? " · SHORTS ALLOWED" : " · LONG ONLY"}
      </div>
      <div className="line dim">
        DATA:{" "}
        {sources.length
          ? sources.map((s, i) => (
              <span key={i} className={s.stale ? "warn" : undefined}>
                {i ? " · " : ""}
                {s.symbol ? `${s.symbol} ` : ""}
                {(s.name ?? "UNKNOWN SOURCE").toUpperCase()}
                {s.age_s != null ? ` ${fmtAge(s.age_s)} OLD` : ""}
                {s.stale ? " STALE" : ""}
              </span>
            ))
          : "SOURCE NOT REPORTED"}
        {l.data_note ? <span className="warn"> · {l.data_note}</span> : null}
        {l.benchmark ? ` · BENCH ${l.benchmark}` : ""}
        {l.costs ? ` · COSTS ${l.costs}` : ""}
      </div>
    </>
  );
}

function Headline({ run }: { run: BtRunFull }) {
  const m = run.metrics;
  const item = (label: string, key: string, signed = true) => (
    <>
      {" · "}
      {label} <span className={signed ? (m[key] == null || m[key] === 0 ? "" : m[key]! > 0 ? "up" : "down") : ""}>{fmtMetric(key, m[key])}</span>
    </>
  );
  return (
    <div className="line">
      FINAL {fmtMetric("final_value", m.final_value)}
      {item("TOTAL", "total_return")}
      {item("ANNUAL", "annual_return")}
      {item("MAX DD", "max_drawdown")}
      {item("SHARPE", "sharpe", false)}
      {item("TRADES", "trade_count", false)}
      {item("VS BENCH", "excess_return")}
    </div>
  );
}
