/**
 * The recorder (REC): start / stop a local recording, list sessions, delete one, and read a session back in the SAME shapes the
 * live panels use (`tas`, `footprint`, `depth`). Uncached (`send`): a session that is still recording grows, so a cached answer would lie.
 */
import { qs, send } from "./core";
import type { FootprintPayload, TasPayload } from "./flowTypes";
import type { RecActive, RecListing, RecordedInfo } from "./recorderTypes";
import type { CdepPayload, Envelope } from "./types";

type Recorded<T> = Envelope<T & { recorded?: RecordedInfo }>;

export const recorderApi = {
  list: () => send<RecListing>("GET", "/api/recorder"),
  start: (symbol: string) => send<RecActive>("POST", "/api/recorder/start", { symbol }),
  stop: (symbol: string) => send<{ id: string; trades: number; snapshots: number }>("POST", "/api/recorder/stop", { symbol }),
  remove: (id: string) => send<{ deleted: string }>("DELETE", `/api/recorder/session/${id}`),
  tas: (id: string, limit: number) => send<Recorded<TasPayload>>("GET", `/api/recorder/tas?${qs({ id, limit: String(limit) })}`),
  footprint: (id: string, interval: string, bars: number) =>
    send<Recorded<FootprintPayload>>("GET", `/api/recorder/footprint?${qs({ id, interval, bars: String(bars) })}`),
  /** Snapshot `index` (0 = oldest, -1 = newest). */
  depth: (id: string, index: number) => send<Recorded<CdepPayload>>("GET", `/api/recorder/depth?${qs({ id, i: String(index) })}`),
};
