/** Payload types of the recorder (REC, and `REC=<id>` on FOOT / TAS / DOM): `/api/recorder/...`. Type-only, so vitest can import it. */

/** One recording that is running right now. */
export interface RecActive {
  symbol: string;
  id: string;
  /** epoch seconds */
  started: number;
  trades: number;
  snapshots: number;
  /** polls that failed and were skipped (never filled in) */
  errors: number;
  last_error: string | null;
  bytes: number;
}

/** One stored session file. `id` is `SYMBOL/YYYY-MM-DD-HHMMSS`. */
export interface RecSession {
  id: string;
  symbol: string;
  /** epoch seconds, from the file name (UTC) */
  started: number;
  bytes: number;
  modified: number;
  recording: boolean;
}

export interface RecListing {
  active: RecActive[];
  sessions: RecSession[];
  /** why a recording ended on its own (symbol -> reason, e.g. `DISK CAP 500 MB`) */
  notes: Record<string, string>;
  total_bytes: number;
  cap_mb: number;
  retention_days: number;
  poll_s: number;
  label: string;
}

/** What a replayed payload says about its session: it is the proof the data is a recording, not live. */
export interface RecordedInfo {
  id: string;
  /** epoch seconds */
  started: number;
  ended?: number | null;
  reason?: string | null;
  /** the file was larger than the reply limit: only its newest part is shown */
  truncated: boolean;
  snapshots?: number;
  /** DOM only: epoch ms the shown snapshot was recorded, its 0-based index and how many there are */
  at?: number;
  index?: number;
  count?: number;
}
