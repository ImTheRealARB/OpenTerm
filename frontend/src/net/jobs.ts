/**
 * Phase 11 jobs store, fed by `J` socket frames (net/socket.ts) and by REST. Frames are queued and applied once per
 * animation frame, so a 10-per-second job costs one store update per frame at most.
 * Perf: `jobs.firstFrameMs` = submitJob() call to the painted frame that shows the job's first J update.
 */
import { afterPaint, gauges, series } from "../perf/metrics";
import { createStore, useStore } from "../state/store";
import { api } from "./api";
import { applyJob, applyJobFrame, isActive, isFinished, parseJobFrame, sortJobs, type JobFrameUpdate, type JobRec } from "./jobFrames";

interface JobsState {
  jobs: Map<string, JobRec>;
  /** Set once a GET /api/jobs has answered; null until then. */
  loadedAt: number | null;
}

export const jobsStore = createStore<JobsState>({ jobs: new Map(), loadedAt: null });

const MAX_JOBS = 300;

function trim(m: Map<string, JobRec>): Map<string, JobRec> {
  if (m.size <= MAX_JOBS) return m;
  const finished = sortJobs(m).filter((j) => isFinished(j.state));
  const out = new Map(m);
  for (const j of finished.slice(Math.max(0, finished.length - (m.size - MAX_JOBS)))) out.delete(j.id);
  return out;
}

const setJobs = (f: (m: Map<string, JobRec>) => Map<string, JobRec>) => jobsStore.set((s) => ({ ...s, jobs: trim(f(s.jobs)) }));

// --- perf: first painted frame per own submission
interface Pending {
  t0: number;
  id: string | null;
}
const pending = new Set<Pending>();
/** Job ids whose first J update has been applied / painted (paint time in ms). */
const framed = new Set<string>();
const painted = new Map<string, number>();

function resolvePending(id: string): void {
  const at = painted.get(id);
  if (at === undefined) return;
  for (const p of pending) {
    if (p.id !== id) continue;
    pending.delete(p);
    const ms = Math.max(0, at - p.t0);
    series.jobsFirstFrame.push(ms);
    gauges.set("jobs.firstFrameMs", ms);
  }
}

// --- socket frames
let queue: JobFrameUpdate[] = [];
let scheduled = false;

const received = new Map<string, number>();

function flush(): void {
  scheduled = false;
  const batch = queue;
  queue = [];
  if (!batch.length) return;
  setJobs((m) => batch.reduce((acc, u) => applyJobFrame(acc, u), m));
  for (const u of batch) {
    if (framed.has(u.id)) continue;
    framed.add(u.id);
    if (framed.size > 500) framed.delete(framed.values().next().value!);
    afterPaint(() => {
      const now = performance.now();
      const recv = received.get(u.id);
      received.delete(u.id);
      if (recv !== undefined) series.jobsFrameToPaint.push(now - recv);
      painted.set(u.id, now);
      if (painted.size > 500) painted.delete(painted.keys().next().value!);
      resolvePending(u.id);
    });
  }
}

/** Called by the socket for every message whose first element is "J". */
export function ingestJobFrame(frame: unknown): void {
  const u = parseJobFrame(frame);
  if (!u) return;
  if (!framed.has(u.id) && !received.has(u.id)) received.set(u.id, performance.now());
  queue.push(u);
  if (!scheduled) {
    scheduled = true;
    requestAnimationFrame(flush);
  }
}

// --- REST
/** Reads the server's list (running + last 50 finished) into the store. Local active jobs the server has not listed yet stay. */
export async function loadJobs(): Promise<void> {
  const { jobs } = await api.jobs();
  setJobs((m) => {
    const fromServer = new Set(jobs.map((j) => j.id));
    let next = new Map([...m].filter(([id, j]) => fromServer.has(id) || isActive(j.state)));
    for (const j of jobs) next = applyJob(next, j);
    return next;
  });
  jobsStore.set((s) => ({ ...s, loadedAt: Date.now() }));
}

export async function submitJob(kind: string, params: unknown): Promise<JobRec> {
  const p: Pending = { t0: performance.now(), id: null };
  for (const q of pending) if (p.t0 - q.t0 > 60_000) pending.delete(q); // jobs that never framed (cached hits)
  pending.add(p);
  try {
    const job = await api.submitJob(kind, params);
    setJobs((m) => applyJob(m, job));
    p.id = job.id;
    resolvePending(job.id);
    return jobsStore.get().jobs.get(job.id) ?? job;
  } catch (e) {
    pending.delete(p);
    throw e;
  }
}

/** Asks the backend to cancel. The job ends in `cancelled` (a frame follows); the answer is merged at once. */
export async function cancelJob(id: string): Promise<void> {
  const job = await api.cancelJob(id);
  setJobs((m) => applyJob(m, { ...job, id }));
}

/** Clears the backend's finished history and drops finished jobs here. Returns how many the backend cleared. */
export async function clearFinished(): Promise<number> {
  const { cleared } = await api.clearFinishedJobs();
  setJobs((m) => new Map([...m].filter(([, j]) => !isFinished(j.state))));
  return cleared;
}

/** Full job including `result` (GET /api/jobs/{id}); also merged into the store. */
export async function fetchJob(id: string): Promise<JobRec> {
  const job = await api.job(id);
  setJobs((m) => applyJob(m, { ...job, id }));
  return jobsStore.get().jobs.get(id) ?? job;
}

// --- hooks
const sortedCache = new WeakMap<Map<string, JobRec>, JobRec[]>();
export function sortedJobs(m: Map<string, JobRec>): JobRec[] {
  let s = sortedCache.get(m);
  if (!s) sortedCache.set(m, (s = sortJobs(m)));
  return s;
}

/** All known jobs, newest first. The array is stable until the store changes. */
export function useJobs(): JobRec[] {
  const m = useStore(jobsStore, (s) => s.jobs);
  return sortedJobs(m);
}

export function useJob(id: string | null | undefined): JobRec | undefined {
  return useStore(jobsStore, (s) => (id ? s.jobs.get(id) : undefined));
}

/** Queued + running jobs: drives `JOBS n` in the status bar. */
export function useRunningJobs(): number {
  return useStore(jobsStore, (s) => {
    let n = 0;
    for (const j of s.jobs.values()) if (isActive(j.state)) n++;
    return n;
  });
}
