/** Quant jobs (RISK, PORT OPT, PORT ATTR, ...). The answer is the job; its `result` is an envelope of a table payload. */
import { send } from "./core";
import type { JobRec } from "./jobFrames";

export const quantApi = {
  run: (fn: string, body: Record<string, unknown>) => send<JobRec>("POST", `/api/quant/${encodeURIComponent(fn)}`, body),
};
