/** SEC fundamentals, filings, insiders and Yahoo holders (FA, FIL, OWN, HDS). `fresh` (F5) skips this client's short cache. */
import type { FaPayload, FaPeriod, FilingsPayload, HoldersPayload, InsidersPayload } from "../functions/secTables";
import { get, TTL } from "./core";
import type { Envelope } from "./types";

export const secApi = {
  fa: (symbol: string, period: FaPeriod, fresh = false) =>
    get<Envelope<FaPayload>>("/api/fa", { symbol, period }, TTL.m5, fresh),
  filings: (symbol: string, form: string, fresh = false) =>
    get<Envelope<FilingsPayload>>("/api/filings", { symbol, form }, TTL.m1, fresh),
  insiders: (symbol: string, fresh = false) =>
    get<Envelope<InsidersPayload>>("/api/insiders", { symbol }, TTL.m2, fresh),
  holders: (symbol: string, fresh = false) =>
    get<Envelope<HoldersPayload>>("/api/holders", { symbol }, TTL.m5, fresh),
};
