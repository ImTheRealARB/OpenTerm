/**
 * JOBS (Phase 11): background jobs, newest first. Rows update from `J` socket frames (net/jobs.ts); nothing here is
 * invented: a failure shows as `ERR: <message>`. `JOBS TEST [steps] [ms]` submits the demo `sleep` job, selects it,
 * then drops the TEST args from the panel's view so a remount (maximize, layout load) never submits again.
 */
import { useEffect, useRef, useState } from "react";
import { Grid, type CellColor, type Column, type GridHandle } from "../components/Grid";
import { registerPanelKeys } from "../keys/panelKeys";
import type { ApiError } from "../net/core";
import { elapsedSec, fmtElapsed, isActive, isFinished, progressText, summarizeJob, type JobRec } from "../net/jobFrames";
import { cancelJob, clearFinished, fetchJob, loadJobs, submitJob, useJobs } from "../net/jobs";
import { replaceView } from "../state/workspace";
import { parseJobsArgs } from "./jobsArgs";
import { navKey } from "../keys/gridNav";
import { useLatest } from "../state/useLatest";
import type { FunctionProps } from "./registry";
import { gridCsv, useCsvExport } from "./tableExport";
import { errText as netErrText } from "../net/errText";

const STATE_COLOR: Record<string, CellColor> = { queued: "dim", running: "acc", done: "up", error: "err", cancelled: "warn" };


/** JOBS messages start with "ERR: ". */
const errText = (e: unknown) => `ERR: ${netErrText(e)}`;

const COLUMNS: Column<JobRec>[] = [
  { title: "ID", width: 9, text: (j) => j.id, color: () => "dim" },
  { title: "JOB", width: 12, text: (j) => j.label ?? j.kind.toUpperCase(), color: () => "acc" },
  { title: "STATE", width: 10, text: (j) => j.state.toUpperCase(), color: (j) => STATE_COLOR[j.state] ?? "fg" },
  { title: "PROGRESS", width: 15, text: (j) => progressText(j.progress), color: (j) => (j.state === "error" ? "err" : "fg") },
  { title: "MESSAGE", width: 30, text: (j) => (j.state === "error" ? `ERR: ${j.error ?? j.msg}` : j.msg), color: (j) => (j.state === "error" ? "err" : "dim") },
  { title: "ELAPSED", width: 8, align: "right", text: (j) => fmtElapsed(elapsedSec(j)), color: () => "dim" },
  { title: "CACHE", width: 6, text: (j) => (j.cached ? "CACHED" : ""), color: () => "warn" },
];

interface Msg {
  text: string;
  cls: "dim" | "warn" | "err" | "up";
}

interface ResultView {
  id: string;
  text: string | null;
  err: string | null;
}

export default function JOBS({ panelId, args }: FunctionProps) {
  const jobs = useJobs();
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<Msg | null>(null);
  const [view, setView] = useState<ResultView | null>(null);
  const [loaded, setLoaded] = useState(false);
  const grid = useRef<GridHandle>(null);
  const wantSel = useRef<string | null>(null);
  const latest = useLatest({ jobs, view });
  useCsvExport(panelId, () => gridCsv("JOBS", COLUMNS, jobs));

  // The server's list on open. Frames keep it live after that.
  useEffect(() => {
    loadJobs()
      .then(() => setErr(null))
      .catch((e: ApiError) => setErr(e.message))
      .finally(() => setLoaded(true));
  }, []);

  // JOBS TEST [steps] [ms]: submit once, select the new job, then forget the args.
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const a = parseJobsArgs(args);
    if (a.kind === "none") return;
    replaceView(panelId, (v) => ({ ...v, args: [] }));
    if (a.kind === "error") {
      setMsg({ text: a.message, cls: "warn" });
      return;
    }
    setMsg({ text: `SUBMITTING TEST JOB: ${a.steps} STEPS x ${a.step_ms} MS…`, cls: "dim" });
    submitJob("sleep", { steps: a.steps, step_ms: a.step_ms })
      .then((j) => {
        wantSel.current = j.id;
        setMsg({ text: `SUBMITTED ${j.id}${j.cached ? " (CACHED RESULT)" : ""}`, cls: "up" });
      })
      .catch((e) => setMsg({ text: errText(e), cls: "err" }));
    // mount only: the args are consumed here
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Keep the cursor on the same job while rows come and go (newest first, so inserts shift the indexes).
  useEffect(() => {
    const g = grid.current;
    if (!g) return;
    const i = wantSel.current ? jobs.findIndex((j) => j.id === wantSel.current) : -1;
    if (i >= 0) g.moveTo(i);
    else wantSel.current = jobs[g.selected()]?.id ?? null;
  }, [jobs]);

  // Elapsed time moves while anything runs: repaint once a second, no row change needed.
  const anyActive = jobs.some((j) => isActive(j.state));
  useEffect(() => {
    if (!anyActive) return;
    const t = window.setInterval(() => grid.current?.redraw(), 1000);
    return () => window.clearInterval(t);
  }, [anyActive]);

  const onSelect = (i: number) => {
    wantSel.current = latest.current.jobs[i]?.id ?? null;
    if (latest.current.view && latest.current.view.id !== wantSel.current) setView(null);
  };

  const cancel = (j: JobRec) => {
    setMsg({ text: `CANCELLING ${j.id}…`, cls: "dim" });
    cancelJob(j.id)
      .then(() => setMsg({ text: `CANCEL SENT FOR ${j.id}`, cls: "warn" }))
      .catch((e) => setMsg({ text: errText(e), cls: "err" }));
  };

  const open = (j: JobRec) => {
    setView({ id: j.id, text: null, err: null });
    fetchJob(j.id)
      .then((full) => setView((v) => (v?.id === j.id ? { id: j.id, text: summarizeJob(full), err: null } : v)))
      .catch((e) => setView((v) => (v?.id === j.id ? { id: j.id, text: null, err: errText(e) } : v)));
  };

  const rerun = async (j: JobRec) => {
    setMsg({ text: `RE-RUNNING ${j.id}…`, cls: "dim" });
    try {
      const params = j.params !== undefined ? j.params : (await fetchJob(j.id)).params;
      if (params === undefined) {
        setMsg({ text: "ERR: THE BACKEND DID NOT REPORT THIS JOB'S PARAMETERS, CANNOT RE-RUN", cls: "err" });
        return;
      }
      const n = await submitJob(j.kind, params);
      wantSel.current = n.id;
      setMsg({ text: `SUBMITTED ${n.id}${n.cached ? " (CACHED RESULT)" : ""}`, cls: "up" });
    } catch (e) {
      setMsg({ text: errText(e), cls: "err" });
    }
  };

  const clear = () => {
    clearFinished()
      .then((n) => setMsg({ text: `CLEARED ${n} FINISHED JOB${n === 1 ? "" : "S"}`, cls: "dim" }))
      .catch((e) => setMsg({ text: errText(e), cls: "err" }));
  };

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        if (e.ctrlKey || e.altKey || e.metaKey) return false;
        const g = grid.current;
        const { jobs: cur, view: v } = latest.current;
        if (e.key === "Escape" && v) {
          setView(null);
          return true;
        }
        const j = cur[g?.selected() ?? -1];
        if (navKey(e, g, cur.length)) return true;
        switch (e.key) {
          case "Escape":
            if (!j || !isActive(j.state)) return false; // falls through
            cancel(j);
            return true;
          case "x":
          case "X":
            if (!j) return true;
            if (isActive(j.state)) cancel(j);
            else setMsg({ text: `${j.id} IS NOT RUNNING (${j.state.toUpperCase()})`, cls: "dim" });
            return true;
          case "Enter":
            if (!j) return true;
            if (isFinished(j.state)) open(j);
            else setMsg({ text: `${j.id} IS ${j.state.toUpperCase()}: NO RESULT YET`, cls: "dim" });
            return true;
          case "r":
          case "R":
            if (j) void rerun(j);
            return true;
          case "c":
          case "C":
            clear();
            return true;
        }
        return false;
      }),
    // everything is read through `latest`; the handlers only set state and call the api
    [panelId, latest],
  );

  const running = jobs.filter((j) => isActive(j.state)).length;
  return (
    <div className="fn">
      <div className="line">
        <span className="acc">JOBS</span> {jobs.length} KNOWN · {running} RUNNING
        {!loaded && !err && <span className="dim"> · LOADING…</span>}
        {err && <span className="err"> · STALE: {err}</span>}
        <span className="dim legend"> · J/K MOVE · ESC/X CANCEL · ENTER RESULT · R RE-RUN · C CLEAR FINISHED · E EXPORT</span>
      </div>
      {msg && <div className={msg.cls}>{msg.text}</div>}
      {view && (
        <div data-testid="jobs-result">
          <div className="acc">RESULT {view.id} · ESC BACK</div>
          {view.text === null && !view.err && <div className="dim">LOADING…</div>}
          {view.err && <div className="err">{view.err}</div>}
          {view.text !== null && <pre>{view.text}</pre>}
        </div>
      )}
      {loaded && jobs.length === 0 && <div className="dim">NO JOBS YET. TRY: JOBS TEST 20 100</div>}
      <Grid ref={grid} columns={COLUMNS} rows={jobs} onSelect={onSelect} />
    </div>
  );
}
