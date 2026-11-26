/** FSRC (ETF screener) payload types. Type-only, so a vitest can import them (see net/types.ts for the same rule). */

/** One fund: [symbol, name, expense ratio in PERCENT (0.03 = 0.03%), total assets in dollars, category, fund family]. A null is "Yahoo sent none". */
export type FsrcRow = [
  symbol: string,
  name: string,
  fee: number | null,
  aum: number | null,
  category: string | null,
  family: string | null,
];

/**
 * What `GET /api/etf/screener?run=&after=` answers. The server builds the table slowly in the background, so each answer carries
 * only the rows added since `after` (a `seq` the last answer returned). `reset: true` means "forget what you hold, this is
 * everything" (first call, or the server restarted). `state` is complete when nothing is left to fetch.
 */
export interface FsrcPayload {
  run: string;
  reset: boolean;
  seq: number;
  rows: FsrcRow[];
  /** ETFs in the symbol file (the size of the full table). */
  universe: number;
  /** ETFs with fund data loaded so far. */
  loaded: number;
  /** ETFs Yahoo has no fund data for (ETNs, brand new funds): counted, never shown with blanks. */
  nodata: number;
  /** ETFs whose fetch kept failing (retried in an hour). */
  failed: number;
  state: "loading" | "paused" | "complete";
  partial: boolean;
  note: string | null;
  universe_source: string;
  file_stamp: string | null;
}
