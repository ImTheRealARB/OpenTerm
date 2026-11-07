/** Background job runner (JOBS and every panel that starts a job). Uncached. `job` carries the result; the list does not. */
import { send } from "./core";
import type { JobRec } from "./jobFrames";

export const jobsApi = {
  jobs: () => send<{ jobs: JobRec[] }>("GET", "/api/jobs"),
  job: (id: string) => send<JobRec>("GET", `/api/jobs/${encodeURIComponent(id)}`),
  submitJob: (kind: string, params: unknown) => send<JobRec>("POST", "/api/jobs", { kind, params }),
  cancelJob: (id: string) => send<JobRec>("DELETE", `/api/jobs/${encodeURIComponent(id)}`),
  clearFinishedJobs: () => send<{ cleared: number }>("DELETE", "/api/jobs?state=finished"),
};
