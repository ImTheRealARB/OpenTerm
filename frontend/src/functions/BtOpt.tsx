/**
 * BT OPT (Phase 26): optimise a strategy's settings. `BT OPT AAPL SMA{10..50:5}>SMA{50..200:25} 1D 10Y [METHOD=GA] [WF=5] ...`
 * One `bt.opt` job runs every parameter set through the normal backtester; this panel shows the answer in four views
 * (V / Shift+V or 1-4): TABLE (sortable runs; S next sort column; Enter runs the selected set as a normal BT in a new panel),
 * HEAT (two parameters as a colour map; X next pair), FRONT (annual return vs max drawdown, the efficient runs highlighted)
 * and WF (walk-forward windows, when WF= was given). The overfitting guards sit above every view: trials, deflated Sharpe,
 * probability of backtest overfitting, edge-of-range and best-region checks. Nothing here is a forecast.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { OPT_EXAMPLE, OPT_USAGE, parseOptArgs, renderRule, type BtOptRequest } from "../bt/optArgs";
import { ChartView, type BarData } from "../chart/ChartView";
import { Grid, type CellColor, type Column, type GridHandle } from "../components/Grid";
import { PanelNote } from "../components/PanelNote";
import { execute } from "../command/execute";
import { fmtNum, fmtPct } from "../format";
import { navKey } from "../keys/gridNav";
import { registerPanelKeys } from "../keys/panelKeys";
import { btApi } from "../net/btApi";
import { errText } from "../net/errText";
import { isActive, progressText } from "../net/jobFrames";
import { adoptJob, cancelJob, fetchJob, useJob } from "../net/jobs";
import type { BtOptResult, BtOptRun, BtOptWindow } from "../net/types";
import { useLatest } from "../state/useLatest";
import { gridCsv, useCsvExport } from "./tableExport";
import "./btOpt.css";

type View = "TABLE" | "HEAT" | "FRONT" | "WF";
type State =
  | { k: "bad"; error: string }
  | { k: "submitting" }
  | { k: "running"; jobId: string; budget: number }
  | { k: "done"; res: BtOptResult }
  | { k: "failed"; error: string };

/** Sort columns S cycles through: [label, value of a run]; every one sorts best first. */
const SORTS: [string, (r: BtOptRun) => number | null | undefined][] = [
  ["FITNESS", (r) => r.fitness],
  ["SHARPE", (r) => r.metrics?.sharpe],
  ["ANNUAL RETURN", (r) => r.metrics?.annual_return],
  ["MAX DD", (r) => r.metrics?.max_drawdown], // drawdowns are negative: the largest is the shallowest
  ["PROFIT FACTOR", (r) => r.metrics?.profit_factor],
  ["TRADES", (r) => r.metrics?.trade_count],
];

const sign = (v: number | null | undefined): CellColor => (v == null || v === 0 ? "fg" : v > 0 ? "up" : "down");
const day = (t: number) => new Date(t * 1000).toISOString().slice(0, 10);

interface Row extends BtOptRun {
  rank: number;
  best: boolean;
}

function tableColumns(res: BtOptResult): Column<Row>[] {
  return [
    { title: "#", width: 5, align: "right", text: (r) => String(r.rank), color: (r) => (r.best ? "acc" : "dim") },
    ...res.params.map((p, j): Column<Row> => ({ title: `${p.name} ${p.where}`.slice(0, 12), width: Math.max(6, Math.min(12, p.name.length + p.where.length + 1)), align: "right", text: (r) => r.values[j], color: () => "val" })),
    { title: res.fit.length > 6 ? "FIT" : `FIT ${res.fit}`, width: 11, align: "right", text: (r) => fmtNum(r.fitness, 3), color: (r) => (r.best ? "acc" : sign(r.fitness)) },
    { title: "SHARPE", width: 8, align: "right", text: (r) => fmtNum(r.metrics?.sharpe, 2), color: (r) => sign(r.metrics?.sharpe) },
    { title: "ANN RET", width: 9, align: "right", text: (r) => (r.metrics?.annual_return == null ? "—" : fmtPct(r.metrics.annual_return * 100)), color: (r) => sign(r.metrics?.annual_return) },
    { title: "MAX DD", width: 9, align: "right", text: (r) => (r.metrics?.max_drawdown == null ? "—" : fmtPct(r.metrics.max_drawdown * 100)), color: () => "down" },
    { title: "PF", width: 6, align: "right", text: (r) => fmtNum(r.metrics?.profit_factor, 2) },
    { title: "TRADES", width: 7, align: "right", text: (r) => fmtNum(r.metrics?.trade_count, 0), color: () => "dim" },
    { title: "FRONT", width: 6, text: (r) => (r.front ? "YES" : ""), color: () => "acc" },
    { title: "NOTE", width: 30, text: (r) => r.error ?? (r.fitness == null ? "NO FITNESS (NO TRADES?)" : ""), color: () => "err" },
  ];
}

const WF_COLS: Column<BtOptWindow>[] = [
  { title: "WIN", width: 4, align: "right", text: (w) => String(w.window), color: () => "dim" },
  { title: "IN SAMPLE", width: 23, text: (w) => `${day(w.is_start)}..${day(w.is_end)}` },
  { title: "OUT OF SAMPLE", width: 23, text: (w) => `${day(w.oos_start)}..${day(w.oos_end)}` },
  { title: "CHOSEN", width: 16, text: (w) => w.values.join(" "), color: () => "val" },
  { title: "IS ANN", width: 9, align: "right", text: (w) => (w.is_annual == null ? "—" : fmtPct(w.is_annual * 100)), color: (w) => sign(w.is_annual) },
  { title: "OOS ANN", width: 9, align: "right", text: (w) => (w.oos_annual == null ? "—" : fmtPct(w.oos_annual * 100)), color: (w) => sign(w.oos_annual) },
  { title: "OOS RET", width: 9, align: "right", text: (w) => fmtPct(w.oos_return * 100), color: (w) => sign(w.oos_return) },
];

/** The BT command for one parameter set (rule strategies only): same symbols, bars, costs and exits as the optimisation. */
function btCommand(req: BtOptRequest, res: BtOptResult, run: BtOptRun): string | null {
  if (res.kind !== "rule") return null;
  const o = req.options;
  const opts = [o.short ? "SHORT" : "", o.fees_bps != null ? `FEES=${o.fees_bps}` : "", o.slip_bps != null ? `SLIP=${o.slip_bps}` : "",
    o.cash != null ? `CASH=${o.cash}` : "", o.stop_pct != null ? `STOP=${o.stop_pct}` : "", o.target_pct != null ? `TARGET=${o.target_pct}` : "",
    o.fill ? "FILL=INTRABAR" : ""].filter(Boolean);
  return ["BT", res.symbols.join(","), renderRule(res.template, run.values).replace(/\s+/g, " "), res.interval, res.range, ...opts].join(" ");
}

export default function BtOpt({ panelId, args }: { panelId: number; args: string[] }) {
  const parsed = useMemo(() => parseOptArgs(args), [args]);
  const [state, setState] = useState<State>({ k: "submitting" });
  const [view, setView] = useState<View>("TABLE");
  const [sortAt, setSortAt] = useState(0);
  const [pair, setPair] = useState(0);
  const [msg, setMsg] = useState<string | null>(null);
  const grid = useRef<GridHandle>(null);
  const job = useJob(state.k === "running" ? state.jobId : null);

  const load = (jobId: string) =>
    fetchJob(jobId)
      .then((full) => setState(full.result ? { k: "done", res: full.result as BtOptResult } : { k: "failed", error: "THE JOB FINISHED WITHOUT A RESULT" }))
      .catch((e) => setState({ k: "failed", error: errText(e) }));

  useEffect(() => {
    if (!parsed.ok) return setState({ k: "bad", error: parsed.error });
    setState({ k: "submitting" });
    btApi
      .opt(parsed.req)
      .then((j) => {
        const rec = adoptJob(j);
        if (rec.state === "done") load(rec.id);
        else setState({ k: "running", jobId: rec.id, budget: j.budget });
      })
      .catch((e) => setState({ k: "failed", error: errText(e) }));
     
  }, [parsed]);

  // An optimisation can run for minutes. Its progress normally arrives as WebSocket `J` frames, but a frame lost while the
  // socket reconnects would leave the panel waiting forever, so the job is also re-read every 3 s while it runs (one small GET).
  const runningId = state.k === "running" ? state.jobId : null;
  useEffect(() => {
    if (!runningId) return;
    const timer = setInterval(() => {
      fetchJob(runningId).catch(() => {}); // a failed re-read is retried 3 s later; the job effect shows real failures
    }, 3000);
    return () => clearInterval(timer);
  }, [runningId]);

  useEffect(() => {
    if (!job || state.k !== "running") return;
    if (job.state === "error") return setState({ k: "failed", error: job.error ?? job.msg ?? "THE JOB FAILED" });
    if (job.state === "cancelled") return setState({ k: "failed", error: "CANCELLED" });
    if (job.state === "done") load(job.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reacts to the job record only
  }, [job]);

  const res = state.k === "done" ? state.res : null;
  const views = useMemo<View[]>(() => (res?.wf ? ["TABLE", "HEAT", "FRONT", "WF"] : ["TABLE", "HEAT", "FRONT"]), [res]);
  const shown: View = views.includes(view) ? view : "TABLE";
  const rows = useMemo<Row[]>(() => {
    if (!res) return [];
    const get = SORTS[sortAt][1];
    const key = (r: BtOptRun) => {
      const v = get(r);
      return v == null || Number.isNaN(v) ? -Infinity : v;
    };
    return res.runs
      .map((r, k) => ({ ...r, rank: 0, best: k === res.best }))
      .sort((a, b) => key(b) - key(a))
      .map((r, k) => ({ ...r, rank: k + 1 }));
  }, [res, sortAt]);
  const columns = useMemo(() => (res ? tableColumns(res) : []), [res]);
  const pairs = useMemo<[number, number][]>(() => {
    const n = res?.params.length ?? 0;
    const out: [number, number][] = [];
    for (let a = 0; a < n; a++) for (let b = a + 1; b < n; b++) out.push([a, b]);
    return n === 1 ? [[0, 0]] : out;
  }, [res]);

  useEffect(() => {
    if (shown === "TABLE" || shown === "WF") grid.current?.moveTo(0);
  }, [shown, res, sortAt]);

  const latest = useLatest({ res, rows, shown, views, pairs, state, job, parsed });
  useCsvExport(panelId, () => {
    const { res: r, rows: rs } = latest.current;
    return r ? gridCsv(`BT_OPT_${r.symbols.slice(0, 3).join("-")}`, tableColumns(r), rs) : null;
  });

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const { res: r, rows: rs, shown: v, views: vs, pairs: ps, state: s, job: j, parsed: p } = latest.current;
        if ((e.key === "x" || e.key === "Escape") && s.k === "running" && j && isActive(j.state)) {
          setMsg(`CANCELLING ${j.id}…`);
          cancelJob(j.id).catch((err) => setMsg(`ERR: ${errText(err)}`));
          return true;
        }
        if (!r) return false;
        if (e.key === "v" || e.key === "V") {
          const i = vs.indexOf(v);
          setView(vs[(i + (e.key === "V" ? vs.length - 1 : 1)) % vs.length]);
          return true;
        }
        const d = Number(e.key);
        if (d >= 1 && d <= vs.length) return setView(vs[d - 1]), true;
        if (v === "TABLE") {
          if (navKey(e, grid.current, rs.length)) return true;
          if (e.key === "s") return setSortAt((k) => (k + 1) % SORTS.length), true;
          if (e.key === "Enter" && p.ok) {
            const row = rs[grid.current?.selected() ?? 0];
            const cmd = row && btCommand(p.req, r, row);
            if (!cmd) setMsg("ENTER: A PYTHON STRATEGY'S SET RUNS ONLY HERE; PUT THE VALUES IN ITS CONSTANTS WITH BT EDIT");
            else execute(cmd, { newPanel: true });
            return true;
          }
        }
        if (v === "HEAT" && e.key === "x" && ps.length > 1) return setPair((k) => (k + 1) % ps.length), true;
        if (v === "WF" && r.wf && navKey(e, grid.current, r.wf.windows.length)) return true;
        return false;
      }),
    [panelId, latest],
  );

  return (
    <div className="fn bt bt-opt">
      <div className="line">
        <span className="acc">BT OPT </span>
        {res ? `${res.symbols.join(",")} ${res.shown} ${res.interval} ${res.range} · ${res.method} · FIT ${res.fit}${res.method !== "GRID" ? ` · SEED ${res.seed}` : ""}` : parsed.ok ? (parsed.req.rule ?? `@${parsed.req.strategy}`) : ""}
      </div>
      {state.k === "bad" && (
        <>
          <PanelNote kind="error" hint={OPT_EXAMPLE}>ERR: {state.error}</PanelNote>
          <div className="dim">{OPT_USAGE}</div>
        </>
      )}
      {state.k === "submitting" && <PanelNote kind="loading">FETCHING BARS AND STARTING THE OPTIMISATION…</PanelNote>}
      {state.k === "running" && (
        <div className="line">
          <span className="acc">OPTIMISING </span>
          {progressText(job?.progress ?? 0)} <span className="dim">{job?.msg ?? job?.state.toUpperCase() ?? "QUEUED"} · UP TO {state.budget} BACKTESTS · X CANCEL</span>
        </div>
      )}
      {state.k === "failed" && <PanelNote kind="error" hint={OPT_EXAMPLE}>ERR: {state.error}</PanelNote>}
      {msg && <div className="dim">{msg}</div>}
      {res && (
        <>
          <div className="line warn">{res.labels.headline} · {res.labels.prices} CLOSES · FEES {fmtNum(res.labels.fees_bps, 0)} BPS · SLIP {fmtNum(res.labels.slip_bps, 0)} BPS{res.labels.stops ? ` · ${res.labels.stops}` : ""}</div>
          <Guards res={res} />
          <div className="line">
            VIEW <span className="acc bt-opt-view">{shown}</span>
            <span className="dim legend"> · V NEXT VIEW (1-{views.length}: {views.join(" ")}){shown === "TABLE" ? ` · S SORT (${SORTS[sortAt][0]}) · ENTER RUN AS BT · J/K MOVE · E CSV` : shown === "HEAT" && pairs.length > 1 ? " · X NEXT PAIR" : ""}</span>
          </div>
          {shown === "TABLE" && <Grid ref={grid} columns={columns} rows={rows} />}
          {shown === "HEAT" && <Heat res={res} pair={pairs[pair % pairs.length] ?? [0, 0]} />}
          {shown === "FRONT" && <Front res={res} />}
          {shown === "WF" && res.wf && <Walk res={res} gridRef={grid} />}
        </>
      )}
    </div>
  );
}

/** The overfitting guards (spec item 3), always next to the winner. */
function Guards({ res }: { res: BtOptResult }) {
  const g = res.guards;
  const best = res.best != null ? res.runs[res.best] : null;
  const pbo = g.pbo?.pbo;
  return (
    <>
      <div className="line bt-opt-best">
        BEST: {best ? <span className="acc">{res.params.map((p, j) => `${p.name}=${best.values[j]}`).join(" ")} · FIT {fmtNum(best.fitness, 3)}</span> : <span className="err">NO RUN HAS A FITNESS</span>}
        <span className="dim"> · <span data-term="TRIALS">{g.trials} TRIALS</span>{g.failed ? ` · ${g.failed} FAILED` : ""}{g.no_fitness ? ` · ${g.no_fitness} WITHOUT FITNESS` : ""}</span>
      </div>
      <div className="line bt-opt-guards">
        <span data-term="DEFLATED SHARPE">DEFLATED SHARPE</span>{" "}
        {g.dsr ? <span className={g.dsr.dsr >= 0.95 ? "up" : "warn"}>{fmtNum(g.dsr.dsr * 100, 0)}%</span> : <span className="dim">N/A (NEEDS 3+ TRIALS AND 30+ BARS)</span>}
        {" · "}
        <span data-term="PBO">PROB. OF BACKTEST OVERFITTING</span>{" "}
        {pbo != null ? <span className={pbo < 0.2 ? "up" : pbo < 0.5 ? "warn" : "err"}>{fmtNum(pbo * 100, 0)}%</span> : <span className="dim">N/A (NEEDS 2+ RUNS)</span>}
        {g.pbo ? <span className="dim"> ({g.pbo.splits} SPLITS)</span> : null}
        {g.edge.length ? <span className="warn"> · EDGE OF RANGE: {g.edge.join(" ")} (WIDEN THE RANGE)</span> : null}
        {g.plateau && g.plateau.mean != null ? (
          <span className="dim"> · <span data-term="BEST REGION">BEST REGION</span>: {g.plateau.neighbours} NEIGHBOURS AVERAGE {fmtNum(g.plateau.mean, 3)} VS {fmtNum(g.plateau.best, 3)}</span>
        ) : null}
      </div>
    </>
  );
}

/** Heat map of two parameters (spec item 2): each cell is the best fitness among runs with those two values. */
function Heat({ res, pair }: { res: BtOptResult; pair: [number, number] }) {
  const [a, b] = pair;
  const pa = res.params[a];
  const pb = res.params[b];
  const one = a === b;
  const cells = useMemo(() => {
    const m = new Map<string, number>();
    for (const r of res.runs) {
      if (r.fitness == null) continue;
      const key = one ? `${r.i[a]}` : `${r.i[a]}|${r.i[b]}`;
      const cur = m.get(key);
      if (cur === undefined || r.fitness > cur) m.set(key, r.fitness);
    }
    return m;
  }, [res, a, b, one]);
  const vals = [...cells.values()];
  // Colour = meaning: green above the neutral level, red below, stronger further away. Neutral is 0 (1 for PF; the
  // starting cash for NET), so the map reads the same way as the table's signed colours.
  const fv = res.runs.find((r) => r.metrics?.final_value != null && r.metrics?.total_return != null)?.metrics;
  const mid = res.fit === "PF" ? 1 : res.fit === "NET" && fv ? (fv.final_value as number) / (1 + (fv.total_return as number)) : 0;
  const span = Math.max(1e-12, ...vals.map((v) => Math.abs(v - mid)));
  const best = res.best != null ? res.runs[res.best] : null;
  const bg = (v: number | undefined) =>
    v === undefined ? undefined : `color-mix(in srgb, var(${v >= mid ? "--up" : "--down"}) ${Math.round((Math.abs(v - mid) / span) * 70) + 8}%, transparent)`;
  const colsVals = one ? [""] : pb.values;
  return (
    <div className="bt-heat" data-testid="bt-heat">
      <div className="dim">
        ROWS {pa.name} {pa.where} · {one ? "ONE PARAMETER" : `COLUMNS ${pb.name} ${pb.where}`} · CELL = BEST {res.fit}
        {res.params.length > 2 ? " OVER THE OTHER PARAMETERS" : ""} · BOXED = THE WINNER
      </div>
      <table className="heat">
        <thead>
          <tr>
            <th />
            {colsVals.map((v) => <th key={v}>{v}</th>)}
          </tr>
        </thead>
        <tbody>
          {pa.values.map((va, ia) => (
            <tr key={va}>
              <th>{va}</th>
              {colsVals.map((vb, ib) => {
                const v = cells.get(one ? `${ia}` : `${ia}|${ib}`);
                const win = best && best.i[a] === ia && (one || best.i[b] === ib);
                return (
                  <td key={vb} style={{ background: bg(v) }} className={win ? "win" : undefined}>
                    {v === undefined ? "·" : fmtNum(v, 2)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Annual return vs max drawdown of every run, the efficient front joined and highlighted (spec item 7). */
function Front({ res }: { res: BtOptResult }) {
  const pts = res.runs
    .map((r) => ({ x: Math.abs((r.metrics?.max_drawdown ?? NaN) * 100), y: (r.metrics?.annual_return ?? NaN) * 100, front: !!r.front }))
    .filter((p) => Number.isFinite(p.x) && Number.isFinite(p.y));
  if (!pts.length) return <PanelNote kind="empty">NO RUN HAS A RETURN AND A DRAWDOWN</PanelNote>;
  const W = 640, H = 300, L = 48, B = 28;
  const xMax = Math.max(1, ...pts.map((p) => p.x));
  const yMin = Math.min(0, ...pts.map((p) => p.y));
  const yMax = Math.max(0.1, ...pts.map((p) => p.y));
  const sx = (x: number) => L + (x / xMax) * (W - L - 8);
  const sy = (y: number) => H - B - ((y - yMin) / (yMax - yMin || 1)) * (H - B - 8);
  const front = pts.filter((p) => p.front).sort((p, q) => p.x - q.x);
  return (
    <div data-testid="bt-front">
      <div className="dim">
        <span data-term="EFFICIENT FRONT">EFFICIENT FRONT</span>: {front.length} OF {pts.length} RUNS · NO OTHER RUN HAS BOTH MORE RETURN AND A SMALLER DRAWDOWN
      </div>
      <svg className="bt-front" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="annual return against max drawdown">
        <line x1={L} y1={sy(0)} x2={W - 8} y2={sy(0)} className="axis" />
        <line x1={L} y1={8} x2={L} y2={H - B} className="axis" />
        <text x={L} y={H - 8} className="lbl">0%</text>
        <text x={W - 8} y={H - 8} className="lbl" textAnchor="end">MAX DRAWDOWN {fmtNum(xMax, 0)}%</text>
        <text x={L - 4} y={sy(yMax) + 4} className="lbl" textAnchor="end">{fmtNum(yMax, 0)}%</text>
        <text x={L - 4} y={sy(yMin) + 4} className="lbl" textAnchor="end">{fmtNum(yMin, 0)}%</text>
        <text x={L + 4} y={16} className="lbl">ANNUAL RETURN</text>
        {pts.filter((p) => !p.front).map((p, k) => <circle key={k} cx={sx(p.x)} cy={sy(p.y)} r={2.5} className="pt" />)}
        <polyline points={front.map((p) => `${sx(p.x)},${sy(p.y)}`).join(" ")} className="front" />
        {front.map((p, k) => <circle key={`f${k}`} cx={sx(p.x)} cy={sy(p.y)} r={3.5} className="pt-front" />)}
      </svg>
    </div>
  );
}

/** Walk-forward windows and the stitched out-of-sample equity (spec item 4). */
function Walk({ res, gridRef }: { res: BtOptResult; gridRef: React.RefObject<GridHandle | null> }) {
  const wf = res.wf!;
  const data = useMemo<BarData>(() => {
    const n = wf.equity.length;
    const t = new Float64Array(n);
    const c = new Float64Array(n);
    for (let i = 0; i < n; i++) {
      t[i] = wf.equity[i][0];
      c[i] = wf.equity[i][1];
    }
    return { symbol: "OOS EQUITY", interval: res.interval === "1W" ? "1wk" : "1d", tz: "UTC", t, o: c, h: c, l: c, c, v: new Float64Array(n) };
  }, [wf, res.interval]);
  return (
    <>
      <div className="line">
        {wf.anchored ? "ANCHORED" : "ROLLING"} · {wf.n_windows} WINDOWS · OUT-OF-SAMPLE ANNUAL{" "}
        <span className={sign(wf.oos_annual)}>{wf.oos_annual == null ? "—" : fmtPct(wf.oos_annual * 100)}</span> · IN-SAMPLE AVERAGE{" "}
        {wf.is_annual_mean == null ? "—" : fmtPct(wf.is_annual_mean * 100)} · <span data-term="WALK-FORWARD EFFICIENCY">WALK-FORWARD EFFICIENCY</span>{" "}
        <span className={wf.wfe != null && wf.wfe >= 0.5 ? "up" : "warn"}>{wf.wfe == null ? "—" : fmtNum(wf.wfe, 2)}</span>
      </div>
      {res.labels.wf && <div className="dim">{res.labels.wf}</div>}
      <div className="bt-opt-wfchart">
        <ChartView data={data} type="LINE" log={false} readoutLabel="OOS EQUITY" />
      </div>
      <Grid ref={gridRef} columns={WF_COLS} rows={wf.windows} />
    </>
  );
}
