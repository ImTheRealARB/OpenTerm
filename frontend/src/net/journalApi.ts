/** JRNL: the trade journal (`/api/journal/*`). Uncached. Import and delete answer this machine only. */
import { qs, send } from "./core";
import type { JobRec } from "./jobFrames";
import type { JrnlAnalysis, JrnlImportResult, JrnlPreview, JrnlSummary } from "../functions/journalModel";

export const journalApi = {
  summary: () => send<JrnlSummary>("GET", "/api/journal/summary"),
  analysis: (currency?: string) => send<JrnlAnalysis>("GET", `/api/journal/analysis?${qs({ currency })}`),
  preview: (text: string) => send<JrnlPreview>("POST", "/api/journal/preview", { text }),
  importFile: (body: Record<string, unknown>) => send<JrnlImportResult>("POST", "/api/journal/import", body),
  clear: (broker?: string) => send<{ deleted: number }>("DELETE", `/api/journal/trades?${qs({ broker })}`),
  /** Starts the Shadow Account job; the answer is the job (follow it with `useJob`). */
  shadow: (body: Record<string, unknown>) => send<JobRec>("POST", "/api/journal/shadow", body),
};
