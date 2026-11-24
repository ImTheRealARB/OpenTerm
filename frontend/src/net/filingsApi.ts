/** Phase 29 filings functions (FTS, MA, LEGAL, BIO, RELS, ESG): one GET per function, each answering the shared table payload. */
import type { TablePayload } from "../research/tablePayload";
import { get, TTL } from "./core";
import type { Envelope } from "./types";

type Params = Record<string, string | undefined>;

export const filingsApi = {
  /** `/api/filings/<fn>`. `fresh` (F5) skips the client cache; the server caches for a few minutes on its own. */
  get: (fn: string, params: Params, fresh = false) => get<Envelope<TablePayload>>(`/api/filings/${fn}`, params, TTL.m2, fresh),
};
