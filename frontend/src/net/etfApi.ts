/** ETF screener client (FSRC, and the ETF heat map IMAP ETF). */
import { get, TTL } from "./core";
import type { FsrcPayload } from "./etfTypes";
import type { Envelope } from "./types";

export const etfApi = {
  /**
   * The ETF table as the server has built it so far. `run` and `after` come from the previous answer (`run`, `seq`) so only new rows
   * travel; with neither, everything loaded so far comes back. Never cached on this side: a poll must see the new rows.
   */
  screener: (run?: string, after?: number) =>
    get<Envelope<FsrcPayload>>("/api/etf/screener", { run, after: after === undefined ? undefined : String(after) }, TTL.s1, true),
};
