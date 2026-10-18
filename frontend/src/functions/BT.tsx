/**
 * BT (Phase 12): backtest a rule on historical bars. `BT AAPL SMA20>SMA50 1D 5Y [SHORT] [FEES=bps] [SLIP=bps] ...`
 * The rule is checked here first (bt/ruleParse.ts mirrors the backend parser), then POST /api/bt/run starts a job;
 * `J` frames drive the progress line and the finished run is fetched by id. Every result carries the labels of
 * spec decision L (historical simulation, data sources and age, ADJ/RAW, fees, slippage, engine, warm-up).
 * V / Shift+V cycle CHART / METRICS / TRADES / CODE (1-4 pick one; Tab stays the global next-panel key). Nothing is invented: failures show the backend's error.
 * M / W (or `BT MC|WF <SYMBOLS> <RULE> ...`) start a Monte Carlo or walk-forward job on the open run; each result adds a
 * view (MC: text histogram of the shuffled Sharpe ratios; WF: one row per window), numbers straight from Vibe's functions.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { btStructure, lastOsa, NO_OSA } from "../bt/optionsStructure";
import { fmtMetric,METRIC_ROWS, type MetricRow } from "../bt/metricsFormat";
import { BT_USAGE, isBtRun, parseBtArgs, parseRule, type BtRun } from "../bt/ruleParse";
import { fmtP, histogram, MC_NOTE } from "../bt/validationFormat";
import { ChartView, type BarData, type ChartHandle } from "../chart/ChartView";
import { Grid, type CellColor, type Column, type GridHandle } from "../components/Grid";
import { downloadText } from "../csv";
import { fmtAge, fmtNum, fmtPct, fmtPrice } from "../format";
import { registerPanelKeys } from "../keys/panelKeys";
import { ApiError, btApi, type BtMcResult, type BtRunFull, type BtTrade, type BtWfResult, type BtWfWindow } from "../net/api";
import { isActive, progressText } from "../net/jobFrames";
import { adoptJob, cancelJob, fetchJob, useJob } from "../net/jobs";
import { afterPaint, commandStartedAt, gauges, series } from "../perf/metrics";
import { navKey, useLatest } from "./quoteRows";
import BtEditor from "./BtEditor";
import BtRuns from "./BtRuns";
import type { FunctionProps } from "./registry";
import { gridCsv, useCsvExport, type CsvTable } from "./tableExport";

const BASE_VIEWS = ["CHART", "METRICS", "TRADES", "CODE"] as const;
type View = (typeof BASE_VIEWS)[number] | "MC" | "WF";
const EXPORT_USAGE = "USAGE: BT EXPORT <RUNID> [PINE|TRADES|EQUITY|METRICS]  (PINE: rule strategies only; the default is PINE)";
const VAL_NAME = { MC: "MONTE CARLO", WF: "WALK-FORWARD" } as const;

type State =
  | { k: "usage" }
  | { k: "bad"; error: string; rule?: string; col?: number }
  | { k: "later"; text: string }
  | { k: "note"; text: string }
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

const WF_COLS: Column<BtWfWindow>[] = [
  { title: "WIN", width: 5, align: "right", text: (w) => String(w.window), color: () => "dim" },
  { title: "START", width: 11, text: (w) => w.start },
  { title: "END", width: 11, text: (w) => w.end },
  { title: "RETURN", width: 10, align: "right", text: (w) => fmtPct(w.return * 100), color: (w) => signColor(w.return) },
  { title: "SHARPE", width: 8, align: "right", text: (w) => fmtNum(w.sharpe, 2), color: (w) => signColor(w.sharpe) },
  { title: "MAX DD", width: 9, align: "right", text: (w) => fmtPct(w.max_dd * 100), color: (w) => signColor(w.max_dd) },
  { title: "TRADES", width: 7, align: "right", text: (w) => String(w.trades) },
  { title: "WIN RATE", width: 9, align: "right", text: (w) => `${fmtNum(w.win_rate * 100, 1)}%` },
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

function request(a: BtRun, structure?: Record<string, unknown>) {
  return {
    ...(structure ? { structure } : {}),
    ...(a.strategy ? { strategy: a.strategy } : structure ? {} : { rule: a.rule }), symbols: a.symbols, interval: a.interval, range: a.range,
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
  const [mc, setMc] = useState<BtMcResult | null>(null);
  const [wf, setWf] = useState<BtWfResult | null>(null);
  const [valRun, setValRun] = useState<{ kind: "MC" | "WF"; jobId: string } | null>(null);
  const valJob = useJob(valRun?.jobId ?? null);

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
    let structure: Record<string, unknown> | undefined;
    if (a.mkt === "options") {
      const os = lastOsa(a.symbols[0]);
      if (!os) return setState({ k: "failed", error: NO_OSA });
      structure = btStructure(os, a);
    }
    setState({ k: "submitting" });
    setMsg(null);
    const t = performance.now();
    btApi
      .run(request(a, structure))
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

  /** BT SAVE <NAME> <RULE>: a named rule, run later as `BT <SYMBOLS> @<NAME>`. (Python strategies are saved from BT EDIT.) */
  const saveRule = (name: string | undefined, rule: string) => {
    if (!name || !rule.trim()) return setState({ k: "bad", error: "USAGE: BT SAVE <NAME> <RULE>  (PYTHON STRATEGIES: BT EDIT <NAME>, CTRL+S)" });
    const r = parseRule(rule);
    if (!r.ok) return setState({ k: "bad", error: r.error, rule, col: r.col });
    setState({ k: "note", text: `SAVING ${name}…` });
    btApi
      .putStrategy(name, { rule })
      .then((s) => setState({ k: "note", text: `SAVED RULE ${s.name}: ${rule} · RUN IT: BT <SYMBOLS> @${s.name} 1D 5Y` }))
      .catch((e) => setState({ k: "failed", error: errText(e) }));
  };
  const deleteStrategy = (name: string | undefined) => {
    if (!name) return setState({ k: "bad", error: "USAGE: BT DEL <NAME>" });
    btApi
      .deleteStrategy(name)
      .then(() => setState({ k: "note", text: `DELETED STRATEGY ${name.toLowerCase()}` }))
      .catch((e) => setState({ k: "failed", error: errText(e) }));
  };

  /** Server-built export (Pine for rule runs, CSV parts), saved as a file. */
  const exportRun = (id: string | undefined, what = "PINE") => {
    const w = what.toUpperCase();
    if (!id || !(w === "PINE" || ["TRADES", "EQUITY", "METRICS"].includes(w))) return setState({ k: "bad", error: EXPORT_USAGE });
    setState({ k: "note", text: `EXPORTING ${w} OF ${id}…` });
    btApi
      .exportText(id, w === "PINE" ? "pine" : "csv", w.toLowerCase())
      .then((text) => {
        const file = downloadText(w === "PINE" ? `BT_${id}.pine` : `BT_${id}_${w.toLowerCase()}.csv`, text);
        setState({ k: "note", text: `EXPORTED ${file}` });
      })
      .catch((e) => setState({ k: "failed", error: errText(e) }));
  };

  // The command's arguments: validate locally, then submit. A remount (maximize, layout load) re-submits; the
  // backend answers an identical request from its cache at once.
  useEffect(() => {
    const started = commandStartedAt(panelId);
    t0.current = started !== undefined && performance.now() - started < 2000 ? started : null;
    if (!args.length) return setState({ k: "usage" });
    if (!parsed.ok) return setState({ k: "bad", error: parsed.error, rule: parsed.rule, col: parsed.col });
    if (!isBtRun(parsed)) {
      const id = parsed.args[0];
      if (parsed.sub === "RUNS") return setState({ k: "usage" }); // drawn by BtRuns
      if (parsed.sub === "OPEN") return id ? load(id) : setState({ k: "bad", error: "USAGE: BT OPEN <RUNID> (BT RUNS LISTS THE IDS)" });
      if (parsed.sub === "EXPORT") return exportRun(id, parsed.args[1]);
      if (parsed.sub === "SAVE") return saveRule(id, parsed.args.slice(1).join(" "));
      if (parsed.sub === "DEL") return deleteStrategy(id);
      return setState({ k: "bad", error: `BT ${parsed.sub}: UNKNOWN SUBCOMMAND` }); // EDIT / LOAD / RUNS are drawn by their own components
    }
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
  const views = useMemo<View[]>(() => [...BASE_VIEWS, ...(mc ? (["MC"] as const) : []), ...(wf ? (["WF"] as const) : [])], [mc, wf]);
  const shown: View = views.includes(view) ? view : "CHART";

  const finishVal = (kind: "MC" | "WF", result: unknown) => {
    const r = result as { run_id?: string } | null;
    setValRun(null);
    if (!r || r.run_id !== latest.current.run?.id) return;
    if (kind === "MC") setMc(r as BtMcResult);
    else setWf(r as BtWfResult);
    setView(kind);
    setMsg(null);
  };

  const startVal = (kind: "MC" | "WF") => {
    const r = latest.current.run;
    if (!r) return;
    setMsg(`${VAL_NAME[kind]}…`);
    btApi
      .validate(r.id, kind === "MC" ? "mc" : "wf")
      .then((j) => {
        const rec = adoptJob(j);
        if (rec.state === "done" && j.result) finishVal(kind, j.result);
        else setValRun({ kind, jobId: rec.id });
      })
      .catch((e) => setMsg(`ERR: ${errText(e)}`));
  };

  // A new run (or a re-run) drops the old validations; `BT MC|WF ...` starts one as soon as the run is on screen.
  useEffect(() => {
    setMc(null);
    setWf(null);
    setValRun(null);
    if (run && isBtRun(parsed) && parsed.val) startVal(parsed.val);
    // keyed on the run only
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run?.id]);

  // Validation job finished: its result (the done frame carries it, else GET /api/jobs/{id}) becomes a view.
  useEffect(() => {
    if (!valJob || !valRun) return;
    if (valJob.state === "error" || valJob.state === "cancelled") {
      setValRun(null);
      return setMsg(valJob.state === "cancelled" ? "CANCELLED" : `ERR: ${valJob.error ?? valJob.msg ?? "THE JOB FAILED"}`);
    }
    if (valJob.state !== "done") return;
    if (valJob.result) return finishVal(valRun.kind, valJob.result);
    fetchJob(valJob.id)
      .then((full) => finishVal(valRun.kind, full.result))
      .catch((e) => {
        setValRun(null);
        setMsg(`ERR: ${errText(e)}`);
      });
    // reacts to the job record only
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [valJob]);

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
    if (shown === "METRICS" || shown === "TRADES" || shown === "WF") grid.current?.moveTo(0);
  }, [shown, run]);

  const latest = useLatest({ state, view: shown, views, run, metricRows, parsed, job, valJob, valRun, mc, wf });
  const name = run ? `BT_${run.symbols.slice(0, 3).join("-")}` : "BT";
  useCsvExport(panelId, (): CsvTable | null => {
    const { run: r, view: v, metricRows: m } = latest.current;
    if (!r) return null;
    if (v === "METRICS") return gridCsv(`${name}_METRICS`, METRIC_COLS, m, [{ title: "RAW", text: (x) => x.v ?? "" }]);
    if (v === "WF" && latest.current.wf) return gridCsv(`${name}_WALKFORWARD`, WF_COLS, latest.current.wf.windows);
    if (v === "MC" && latest.current.mc) {
      const h = histogram(latest.current.mc.sharpe_samples, HIST_BINS, latest.current.mc.actual_sharpe);
      return { name: `${name}_MONTECARLO`, header: ["SHARPE FROM", "SHARPE TO", "SHUFFLES", "CONTAINS ACTUAL"], rows: h.map((b) => [b.lo, b.hi, b.count, b.actual ? "YES" : ""]) };
    }
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
        const { state: s, view: v, views: vs, run: r, metricRows: m, parsed: p, job: j, valJob: vj, valRun: vr, mc: mcr, wf: wfr } = latest.current;
        // Tab is the global next-panel key and never reaches a panel: V / Shift+V cycle the views, 1-4 pick one.
        if ((e.key === "v" || e.key === "V") && r) {
          const i = vs.indexOf(v);
          setView(vs[(i + (e.key === "V" ? vs.length - 1 : 1)) % vs.length]);
          return true;
        }
        const d = Number(e.key);
        if (r && d >= 1 && d <= vs.length) {
          setView(vs[d - 1]);
          return true;
        }
        if ((v === "METRICS" || v === "TRADES") && r && navKey(e, grid.current, v === "METRICS" ? m.length : r.trades.length)) return true;
        if (v === "WF" && wfr && navKey(e, grid.current, wfr.windows.length)) return true;
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
        if (k === "p" && r) {
          if (!r.rule) setMsg("P: PINE EXPORT NEEDS A RULE STRATEGY (PYTHON CODE CANNOT BE TRANSLATED FAITHFULLY; E EXPORTS CSV)");
          else {
            btApi
              .exportText(r.id, "pine")
              .then((text) => setMsg(`EXPORTED ${downloadText(`BT_${r.id}.pine`, text)}`))
              .catch((err) => setMsg(`ERR: ${errText(err)}`));
          }
          return true;
        }
        if ((k === "m" || k === "w") && r) {
          const kind = k === "m" ? "MC" : "WF";
          if (vr) setMsg(`${VAL_NAME[vr.kind]} IS STILL RUNNING`);
          else if ((kind === "MC" ? mcr : wfr) != null) setView(kind);
          else startVal(kind);
          return true;
        }
        if (vr && vj && isActive(vj.state) && (k === "x" || e.key === "Escape")) {
          setMsg(`CANCELLING ${vj.id}…`);
          cancelJob(vj.id).catch((err) => setMsg(`ERR: ${errText(err)}`));
          return true;
        }
        if (k === "x" || (e.key === "Escape" && s.k === "running")) {
          if (s.k !== "running" || !j || !isActive(j.state)) return k === "x";
          setMsg(`CANCELLING ${j.id}…`);
          cancelJob(j.id).catch((err) => setMsg(`ERR: ${errText(err)}`));
          return true;
        }
        if (k === "s" && r) {
          setMsg(r.code ? "S: COPY THE CODE FROM THE CODE VIEW INTO BT EDIT <NAME> AND PRESS CTRL+S" : "S: BT SAVE <NAME> <RULE> SAVES THIS RULE; PYTHON STRATEGIES ARE SAVED FROM BT EDIT <NAME>");
          return true;
        }
        return false;
      }),
    // everything is read through `latest`
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [panelId, latest],
  );

  if (parsed.ok && parsed.sub === "RUNS") return <BtRuns panelId={panelId} />;
  if (parsed.ok && (parsed.sub === "EDIT" || parsed.sub === "LOAD")) return <BtEditor panelId={panelId} name={parsed.args[0]} />;
  return (
    <div className="fn">
      <Head parsed={isBtRun(parsed) ? parsed : null} run={run} />
      {state.k === "usage" && (
        <>
          <div className="dim">{BT_USAGE}</div>
          <div className="dim">RULE TERMS: CLOSE OPEN HIGH LOW VOLUME SMAn EMAn RSIn HIGHn LOWn RETn NUMBER · OPS: &gt; &lt; &gt;= &lt;= CROSS&gt; CROSS&lt; · AND OR</div>
          <div className="dim">EXAMPLE: BT AAPL SMA20&gt;SMA50 1D 5Y · BT SPY,QQQ RSI14&lt;30 1D 10Y SHORT FEES=5 SLIP=5</div>
          <div className="dim">BT EDIT [NAME] = PYTHON STRATEGY EDITOR · BT SAVE &lt;NAME&gt; &lt;RULE&gt; · BT DEL &lt;NAME&gt; · BT &lt;SYMBOLS&gt; @&lt;NAME&gt; RUNS A SAVED ONE</div>
          <div className="dim">BT RUNS LISTS STORED RUNS (C COMPARES TWO) · BT OPEN &lt;RUNID&gt; · BT EXPORT &lt;RUNID&gt; [PINE|TRADES|EQUITY|METRICS]</div>
          <div className="dim">BT MC|WF &lt;SYMBOLS&gt; &lt;RULE&gt; … RUNS IT, THEN SHUFFLES ITS TRADES (MC) OR SPLITS IT INTO WINDOWS (WF) · M / W ON AN OPEN RUN DO THE SAME</div>
        </>
      )}
      {state.k === "bad" && <BadRule {...state} />}
      {state.k === "later" && <div className="warn">{state.text}</div>}
      {state.k === "note" && <div className="dim">{state.text}</div>}
      {state.k === "submitting" && <div className="dim">FETCHING BARS AND SUBMITTING…</div>}
      {state.k === "running" && (
        <div className="line">
          <span className="acc">RUNNING </span>
          {progressText(job?.progress ?? 0)} <span className="dim">{job?.msg ?? job?.state.toUpperCase() ?? "QUEUED"} · X CANCEL</span>
        </div>
      )}
      {valRun && (
        <div className="line">
          <span className="acc">{VAL_NAME[valRun.kind]} </span>
          {progressText(valJob?.progress ?? 0)} <span className="dim">{valJob?.msg ?? valJob?.state.toUpperCase() ?? "QUEUED"} · X CANCEL</span>
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
            VIEW <span className="bt-view acc">{shown}</span>
            <span className="dim"> · V NEXT VIEW (1-{views.length}: {views.join(" ")}) · M MONTE CARLO · W WALK-FORWARD · R RE-RUN · E EXPORT CSV · P PINE{shown === "CHART" ? " · H/L PAN · +/- ZOOM" : shown === "MC" || shown === "CODE" ? "" : " · J/K MOVE"}</span>
          </div>
          {shown === "CHART" && chartBits && (
            <ChartView key={run.id} ref={chart} data={chartBits.data} compare={chartBits.compare} type="LINE" log={false} indicators={NO_INDICATORS} readoutLabel="EQUITY" lowerPane={chartBits.drawdown} />
          )}
          {shown === "METRICS" && <Grid ref={grid} columns={METRIC_COLS} rows={metricRows} />}
          {shown === "TRADES" && (trades.length ? <Grid ref={grid} columns={TRADE_COLS} rows={trades} /> : <div className="dim">NO TRADES IN THIS RUN</div>)}
          {shown === "CODE" && <pre className="desc">{run.rule ?? run.code ?? (run.strategy ? `STRATEGY ${run.strategy}` : "—")}</pre>}
          {shown === "MC" && mc && <McView mc={mc} />}
          {shown === "WF" && wf && (
            <>
              <WfSummary wf={wf} />
              <Grid ref={grid} columns={WF_COLS} rows={wf.windows} />
            </>
          )}
        </>
      )}
    </div>
  );
}

const NO_INDICATORS: never[] = [];
const HIST_BINS = 20;

function McView({ mc }: { mc: BtMcResult }) {
  const rows = useMemo(() => histogram(mc.sharpe_samples, HIST_BINS, mc.actual_sharpe), [mc]);
  const b = mc.bootstrap;
  return (
    <div>
      <div className="line warn">
        {mc.labels.headline} · {mc.labels.validation}
      </div>
      <div className="line">
        ACTUAL SHARPE <span className="acc">{fmtNum(mc.actual_sharpe, 2)}</span> · SHUFFLED MEAN {fmtNum(mc.simulated_sharpe_mean, 2)} (P5 {fmtNum(mc.simulated_sharpe_p5, 2)} · P95{" "}
        {fmtNum(mc.simulated_sharpe_p95, 2)}) · P-VALUE <span className="acc">{fmtP(mc.p_value_sharpe)}</span>
        <span className="dim"> = SHUFFLES WITH A SHARPE AT LEAST AS HIGH</span>
      </div>
      <div className="line">
        ACTUAL MAX DD <span className="acc">{fmtPct(mc.actual_max_dd * 100)}</span> · P-VALUE <span className="acc">{fmtP(mc.p_value_max_dd)}</span>
        <span className="dim"> = SHUFFLES WITH A DRAWDOWN NO DEEPER · {mc.n_trades} TRADES · {mc.n_simulations} SHUFFLES</span>
      </div>
      <div className="line">
        {b.error ? (
          <span className="err">BOOTSTRAP: {b.error.toUpperCase()}</span>
        ) : (
          <>
            BOOTSTRAP SHARPE {fmtNum((b.confidence ?? 0) * 100, 0)}% CI{" "}
            <span className="acc">
              {fmtNum(b.ci_lower, 2)} TO {fmtNum(b.ci_upper, 2)}
            </span>{" "}
            · MEDIAN {fmtNum(b.median_sharpe, 2)} · SHARPE &gt; 0 IN {fmtP(b.prob_positive)} OF {b.n_bootstrap} RESAMPLES
          </>
        )}
      </div>
      <div className="line dim">{MC_NOTE}</div>
      <pre className="desc" data-testid="mc-hist">
        {"SHUFFLED SHARPE          SHUFFLES\n"}
        {rows.map((r) => `${fmtNum(r.lo, 2).padStart(7)} TO ${fmtNum(r.hi, 2).padStart(6)} ${"█".repeat(r.bar).padEnd(40)} ${String(r.count).padStart(4)}${r.actual ? "  ◄ ACTUAL" : ""}`).join("\n")}
      </pre>
    </div>
  );
}

function WfSummary({ wf }: { wf: BtWfResult }) {
  return (
    <>
      <div className="line warn">
        {wf.labels.headline} · {wf.labels.validation}
      </div>
      <div className="line">
        {wf.profitable_windows} OF {wf.n_windows} WINDOWS PROFITABLE ({fmtP(wf.consistency_rate)}) · RETURN MEAN {fmtPct(wf.return_mean * 100)} STD {fmtNum(wf.return_std * 100, 2)}% · SHARPE MEAN{" "}
        {fmtNum(wf.sharpe_mean, 2)} STD {fmtNum(wf.sharpe_std, 2)}
      </div>
    </>
  );
}

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
