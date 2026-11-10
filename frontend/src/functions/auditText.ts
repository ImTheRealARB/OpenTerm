/** AUDIT stored-text helpers (pure, so vitest loads them without React). Text is outside the hash chain: a purge never breaks it. */

export type PurgeAsk = null | "ONE" | "ALL";

/** What a key does in AUDIT's purge step: P / X ask first, the same key again confirms, any other key cancels. */
export function purgeStep(ask: PurgeAsk, key: string): { ask: PurgeAsk; run: PurgeAsk } {
  const k = key.toLowerCase();
  const want: PurgeAsk = k === "p" ? "ONE" : k === "x" ? "ALL" : null;
  if (want === null) return { ask: null, run: null };
  return ask === want ? { ask: null, run: want } : { ask: want, run: null };
}

/** The status line after a purge (`n` rows removed) and the chain verdict re-read from the backend. */
export function purgeMessage(scope: "ONE" | "ALL", seq: number, n: number, chainOk: boolean | null): string {
  const what = n === 0 ? "NO STORED TEXT TO REMOVE" : scope === "ONE" ? `STORED TEXT OF ENTRY ${seq} REMOVED` : `STORED TEXT OF ${n} ENTRIES REMOVED`;
  const chain = chainOk === null ? "" : chainOk ? " · CHAIN STILL VERIFIES (TEXT IS OUTSIDE THE HASH)" : " · CHAIN BROKEN: SEE ABOVE";
  return what + chain;
}
