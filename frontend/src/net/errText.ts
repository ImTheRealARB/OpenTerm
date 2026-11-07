/**
 * Turns a caught error into the text a panel shows. Pure (it only needs the `ApiError` TYPE), so vitest can run it.
 * An `ApiError` carries the server's message and, often, the reason behind it (`detail`, e.g. "gdelt: rate_limited").
 */
import type { ApiError } from "./core";

/** Just the message ("HTTP 500", "BACKEND DOWN", the server's own words). Used where the detail would only add noise. */
export function errMessage(e: unknown): string {
  const a = e as ApiError | null | undefined;
  return a?.message ?? String(e);
}

/**
 * The message plus the server's detail when it sent one. `style` picks how the detail is attached:
 * "paren" = `message (detail)` (most panels), "colon" = `message: detail` (the BT strategy editor reads better that way).
 */
export function errText(e: unknown, style: "paren" | "colon" = "paren"): string {
  const detail = (e as ApiError | null | undefined)?.detail;
  if (!detail) return errMessage(e);
  return style === "colon" ? `${errMessage(e)}: ${detail}` : `${errMessage(e)} (${detail})`;
}
