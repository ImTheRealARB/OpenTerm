/**
 * Phase 11 job runner, client side, pure part (no window, no api imports: vitest runs this in Node).
 * Server frame: ["J", {id, kind, state, progress, msg, cached}]. REST jobs carry more (label, params, times, result).
 */

export type JobState = "queued" | "running" | "done" | "error" | "cancelled";

const STATES: readonly string[] = ["queued", "running", "done", "error", "cancelled"];
const RANK: Record<JobState, number> = { queued: 0, running: 1, done: 2, error: 2, cancelled: 2 };

export interface JobFrameUpdate {
  id: string;
  kind: string;
  state: JobState;
  progress: number;
  msg: string;
  cached: boolean;
}

/** A job as the client holds it: the frame fields plus whatever REST told us. */
export interface JobRec extends JobFrameUpdate {
  label?: string;
  params?: unknown;
  error?: string | null;
  created_at?: number | null;
  started_at?: number | null;
  finished_at?: number | null;
  result?: unknown;
  /** Local epoch seconds when this client first saw the job / first saw it finished (fallbacks for elapsed). */
  seen_at?: number;
  end_at?: number;
}

export const isFinished = (s: JobState): boolean => RANK[s] === 2;
export const isActive = (s: JobState): boolean => RANK[s] < 2;

const clamp01 = (p: number) => (p < 0 ? 0 : p > 1 ? 1 : p);

/** A valid J frame as an update, or null for anything else. */
export function parseJobFrame(frame: unknown): JobFrameUpdate | null {
  if (!Array.isArray(frame) || frame[0] !== "J") return null;
  const b = frame[1] as Record<string, unknown> | null | undefined;
  if (!b || typeof b !== "object") return null;
  const { id, kind, state, progress, msg, cached } = b;
  if (typeof id !== "string" || !id || typeof kind !== "string") return null;
  if (typeof state !== "string" || !STATES.includes(state)) return null;
  if (typeof progress !== "number" || Number.isNaN(progress)) return null;
  if (typeof msg !== "string" || typeof cached !== "boolean") return null;
  return { id, kind, state: state as JobState, progress: clamp01(progress), msg, cached };
}

const nowSec = () => Date.now() / 1000;

/** True when `next` must not replace `cur`: a finished job never goes back, a running one never goes back to queued. */
function regresses(cur: JobState, next: JobState): boolean {
  return RANK[next] < RANK[cur] && !(isFinished(cur) && isFinished(next));
}

/** New map with the frame merged into any existing job (label and params are kept). Late frames never move a job back. */
export function applyJobFrame(map: Map<string, JobRec>, u: JobFrameUpdate, now = nowSec()): Map<string, JobRec> {
  const next = new Map(map);
  const cur = map.get(u.id);
  if (!cur) {
    next.set(u.id, { ...u, seen_at: now, ...(isFinished(u.state) ? { end_at: now } : {}) });
    return next;
  }
  if (regresses(cur.state, u.state)) return next;
  const rec: JobRec = { ...cur, ...u };
  if (isFinished(u.state) && !isFinished(cur.state)) rec.end_at = now;
  next.set(u.id, rec);
  return next;
}

/**
 * Merges a REST job (any subset of fields, validated one by one) into the map. Never regresses state, and an active
 * job keeps the further-along progress and message when the REST copy is older than the frames already applied.
 */
export function applyJob(map: Map<string, JobRec>, job: Partial<JobRec> & { id: string }, now = nowSec()): Map<string, JobRec> {
  const next = new Map(map);
  const cur = map.get(job.id);
  const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : v === null ? null : undefined);
  const str = (v: unknown) => (typeof v === "string" ? v : undefined);
  const incoming: Partial<JobRec> = {};
  const set = <K extends keyof JobRec>(k: K, v: JobRec[K] | undefined) => {
    if (v !== undefined) incoming[k] = v;
  };
  set("kind", str(job.kind));
  set("label", str(job.label));
  if (job.params !== undefined) incoming.params = job.params;
  if (job.result !== undefined) incoming.result = job.result;
  if (job.error === null || typeof job.error === "string") incoming.error = job.error;
  set("created_at", num(job.created_at));
  set("started_at", num(job.started_at));
  set("finished_at", num(job.finished_at));
  if (typeof job.cached === "boolean") incoming.cached = job.cached;
  const state = typeof job.state === "string" && STATES.includes(job.state) ? (job.state as JobState) : undefined;
  const progress = typeof job.progress === "number" && !Number.isNaN(job.progress) ? clamp01(job.progress) : undefined;
  const msg = str(job.msg);

  if (!cur) {
    next.set(job.id, {
      kind: "",
      state: state ?? "queued",
      progress: progress ?? 0,
      msg: msg ?? "",
      cached: false,
      ...incoming,
      id: job.id,
      seen_at: now,
      ...(state && isFinished(state) ? { end_at: now } : {}),
    } as JobRec);
    return next;
  }
  const rec: JobRec = { ...cur, ...incoming };
  const stale = state !== undefined && regresses(cur.state, state);
  const behind = isActive(cur.state) && progress !== undefined && progress < cur.progress;
  if (state !== undefined && !stale) rec.state = state;
  if (!stale && !behind) {
    if (progress !== undefined) rec.progress = progress;
    if (msg !== undefined) rec.msg = msg;
  }
  if (isFinished(rec.state) && !isFinished(cur.state)) rec.end_at = now;
  next.set(job.id, rec);
  return next;
}

/** `#####.....  52%`: ten cells, a hash per completed tenth, then the right-aligned percent. */
export function progressText(p: number): string {
  const v = Number.isFinite(p) ? clamp01(p) : 0;
  const n = Math.min(10, Math.floor(v * 10 + 1e-9));
  const pct = String(Math.round(v * 100)).padStart(3);
  return `${"#".repeat(n)}${".".repeat(10 - n)} ${pct}%`;
}

/** Seconds a job has run (or ran for), from server times when present, else from when this client saw it. */
export function elapsedSec(j: JobRec, now = nowSec()): number | null {
  const start = j.started_at ?? (j.state === "queued" ? null : j.created_at) ?? j.seen_at ?? null;
  if (start == null) return null;
  const end = isFinished(j.state) ? (j.finished_at ?? j.end_at ?? now) : now;
  return Math.max(0, end - start);
}

export function fmtElapsed(s: number | null): string {
  if (s == null) return "";
  if (s < 60) return `${s.toFixed(1)}S`;
  const m = Math.floor(s / 60);
  return `${m}M${String(Math.floor(s % 60)).padStart(2, "0")}S`;
}

/** Newest first. */
export function sortJobs(map: Map<string, JobRec>): JobRec[] {
  const t = (j: JobRec) => j.created_at ?? j.seen_at ?? 0;
  return [...map.values()].sort((a, b) => t(b) - t(a) || (a.id < b.id ? 1 : -1));
}

/** A short JSON summary for the result view. Real fields only, cut at `max` characters. */
export function summarizeJob(j: JobRec, max = 1500): string {
  const view = { id: j.id, kind: j.kind, label: j.label, state: j.state, cached: j.cached, error: j.error ?? undefined, params: j.params, result: j.result };
  let text = JSON.stringify(view, null, 1) ?? "";
  if (text.length > max) text = `${text.slice(0, max)}\n... TRUNCATED (${text.length - max} MORE CHARACTERS)`;
  return text;
}
