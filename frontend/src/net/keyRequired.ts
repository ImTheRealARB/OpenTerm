/** Phase 11: the HTTP 424 "KEY REQUIRED" envelope. Pure, so vitest can test it (no `window`). */
export interface KeyRequiredInfo {
  /** Env name of the missing key, e.g. FINNHUB. */
  key: string;
  /** Ready-to-show line, e.g. "KEY REQUIRED: set FINNHUB in APIKEYS". */
  detail: string;
}

/** Returns the key and the line to show for a 424 envelope; null for any other failure. */
export function keyRequired(status: number, body: unknown): KeyRequiredInfo | null {
  if (status !== 424 || typeof body !== "object" || body === null) return null;
  const { key, detail } = body as { key?: unknown; detail?: unknown };
  if (typeof key !== "string" || !key || typeof detail !== "string" || !detail) return null;
  return { key, detail };
}
