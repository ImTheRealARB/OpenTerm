/**
 * Phase 15: runs a quant job (`POST /api/quant/{fn}`) and waits for its table payload. The job is adopted into the jobs store so its
 * J frames show in JOBS; progress is reported while it runs. `GET /api/jobs/{id}` is polled every 500 ms, so a missing J frame
 * (or a job that finished before the socket said so) still ends. Needs the browser (net/core): not unit-tested.
 */
import { ApiError } from "../net/core";
import { jobsApi } from "../net/jobsApi";
import { portfolioApi } from "../net/portfolioApi";
import { quantApi } from "../net/quantApi";
import type { Envelope, ValRow } from "../net/types";
import { isFinished } from "../net/jobFrames";
import type { JobRec } from "../net/jobFrames";
import { adoptJob, jobsStore } from "../net/jobs";
import type { TablePayload } from "../research/tablePayload";
import { quantBody } from "./quantArgs";

export interface RunCtx {
  /** Status text while the job runs ("40% factor 10/24"). */
  progress: (text: string) => void;
  /** A one-line note shown above the table (SAVED ..., ADDED ...). */
  say: (text: string) => void;
  /** False once the panel is gone or its arguments changed: stop polling. */
  alive: () => boolean;
}

const POLL_MS = 500;
const GIVE_UP_MS = 15 * 60_000;
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

function envelopeOf(job: JobRec): Envelope<TablePayload> {
  if (job.state === "error") throw new ApiError(500, job.error ?? "JOB FAILED", "unavailable");
  if (job.state === "cancelled") throw new ApiError(499, "JOB CANCELLED", "unavailable");
  const r = job.result as Envelope<TablePayload> | null | undefined;
  if (!r || typeof r !== "object" || !r.data) throw new ApiError(502, "JOB HAS NO RESULT", "unavailable");
  return r;
}

const progressText = (j: JobRec) => `${Math.round((j.progress ?? 0) * 100)}%${j.msg ? ` ${j.msg}` : ""}`;

export async function runQuant(fn: string, params: Record<string, string | string[]>, ctx: RunCtx): Promise<Envelope<TablePayload>> {
  const fetchFull = () => jobsApi.job(id).then((j) => adoptJob({ ...j, id }));
  const posted = await quantApi.run(fn, quantBody(fn, params));
  const id = posted.id;
  adoptJob(posted);
  let cur: JobRec = posted;
  const t0 = Date.now();
  for (;;) {
    // a cache hit answers the POST with the finished job and its result
    if (isFinished(cur.state) && (cur.result !== undefined || cur.state !== "done")) return envelopeOf(cur);
    if (!isFinished(cur.state)) {
      if (!ctx.alive()) throw new ApiError(499, "CANCELLED", "unavailable");
      if (Date.now() - t0 > GIVE_UP_MS) throw new ApiError(504, "JOB TIMED OUT", "unavailable");
      ctx.progress(progressText(jobsStore.get().jobs.get(id) ?? cur));
      await sleep(POLL_MS);
    }
    cur = await fetchFull();
    if (isFinished(cur.state) && cur.result === undefined && cur.state === "done") return envelopeOf(cur); // throws: no result
  }
}

/** Merges one valuation (PORT ATTR ADD) into the stored table: the same date is replaced; the rows stay sorted by date. */
export async function addValuation(name: string, row: ValRow): Promise<number> {
  const { rows } = await portfolioApi.vals(name);
  const next = [...rows.filter((r) => r.date !== row.date), row].sort((a, b) => a.date.localeCompare(b.date));
  await portfolioApi.putVals(name, next);
  return next.length;
}

/** PORT ATTR DEL: removes the valuation of that date. */
export async function deleteValuation(name: string, date: string): Promise<boolean> {
  const { rows } = await portfolioApi.vals(name);
  const next = rows.filter((r) => r.date !== date);
  if (next.length === rows.length) return false;
  await portfolioApi.putVals(name, next);
  return true;
}
