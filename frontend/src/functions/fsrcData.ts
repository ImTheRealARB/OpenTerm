/**
 * The ETF table as the client holds it (pure, unit-tested). The server sends rows in installments (see net/etfTypes.ts `FsrcPayload`);
 * `mergeFsrc` folds each installment into what is already held, keyed by symbol so a fund fetched again replaces its old row.
 */
import type { FsrcPayload, FsrcRow } from "../net/etfTypes";

export interface FsrcHeld {
  /** The server run these rows came from, and how far into its feed we are: both are sent back with the next poll. */
  run: string | null;
  seq: number;
  rows: Map<string, FsrcRow>;
}

export const FSRC_EMPTY: FsrcHeld = { run: null, seq: 0, rows: new Map() };

/** A new object every time (React state compares by identity). `reset` means "this is everything: drop what you hold". */
export function mergeFsrc(held: FsrcHeld, p: FsrcPayload): FsrcHeld {
  const rows = p.reset ? new Map<string, FsrcRow>() : new Map(held.rows);
  for (const r of p.rows) rows.set(r[0], r);
  return { run: p.run, seq: p.seq, rows };
}
