/** Server self-reports: provider health (SOURCES, the status bar) and the log records (LOG). */
import { get, TTL } from "./core";
import type { LogRecord, SourcesPayload } from "./types";

export const systemApi = {
  sources: () => get<SourcesPayload>("/api/sources", undefined, TTL.s1),
  log: (after: number) => get<{ records: LogRecord[] }>(`/api/log?after=${after}`, undefined, 0),
};
