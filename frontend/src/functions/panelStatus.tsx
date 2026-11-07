/**
 * The ONE place that words a panel's data status and its failures (it replaces the old macro/SEC copies in
 * the former macroUi.tsx and secPanel.tsx, which used different wording for the same state).
 *
 *   EnvStatus  " · SOURCE · AGE 2S" / " · SOURCE · STALE 10M" / " · X DOWN, VIA FALLBACK" / " · LOADING…"
 *   ErrorLine  KEY REQUIRED / PROVIDER DOWN: … / the error text, plus "SHOWING STALE DATA" when older data is on screen
 *
 * Keep the visible text here only: e2e specs match it (STALE 10M, AGE 2S, X DOWN, VIA FALLBACK, PROVIDER DOWN: ...).
 */
import type { ReactNode } from "react";
import { fmtAge } from "../format";
import type { ApiError } from "../net/core";
import type { Envelope } from "../net/types";
import { isKeyRequired, KeyRequiredLine } from "./KeyRequiredLine";

// ---- SEC states that ErrorLine explains in more detail (the SEC panels FA, FIL, OWN, HDS ... share them) ----

export const US_ONLY = "SEC DATA COVERS US FILERS ONLY";
/** SEC answers 403 when no contact User-Agent is set: the error detail mentions it, and the fix is the same everywhere. */
export const SEC_UA_RE = /SEC_USER_AGENT|403 from SEC/;
export const SEC_UA_HINT = 'SEC REJECTED THE REQUEST: SET SEC_USER_AGENT="Your Name you@yourdomain" IN .env AND RESTART THE BACKEND';

// Providers whose raw id is not what a reader should see. Everything else is just upper-cased.
const SOURCE_NAMES: Record<string, string> = { sec: "SEC EDGAR", yahoo_own: "YAHOO FINANCE", fixtures: "FIXTURES" };
export const sourceName = (s: string | null | undefined) => SOURCE_NAMES[s ?? ""] ?? (s ?? "").toUpperCase();

/**
 * The status tail of a panel title line: source, age (or STALE age), fallback note, then LOADING.
 * `extra` is for a panel's own bit that belongs before LOADING (the SEC Header puts its filing date there).
 */
export function EnvStatus({ env, loading, extra }: { env: Envelope<unknown> | null; loading: boolean; extra?: ReactNode }) {
  return (
    <>
      {env && ` · ${sourceName(env.source)}`}
      {env && <span className={env.stale ? "warn" : "dim"}> · {env.stale ? "STALE " : "AGE "}{fmtAge(env.age_s)}</span>}
      {env && env.fallback_from.length > 0 && <span className="warn"> · {env.fallback_from.join(",").toUpperCase()} DOWN, VIA FALLBACK</span>}
      {extra}
      {loading && <span className="dim"> · LOADING…</span>}
    </>
  );
}

/**
 * A failed load. When older data is still on screen it is said to be STALE rather than hidden.
 * `usage` (optional) is the command's syntax, shown only for a bad-request error.
 */
export function ErrorLine({ error, hasData, usage }: { error: ApiError | null; hasData: boolean; usage?: string }) {
  if (!error) return null;
  if (isKeyRequired(error)) return <KeyRequiredLine error={error} />;
  // "US filers only" is a coverage state, not a failure, so it is shown in the warning colour.
  if (error.message === US_ONLY)
    return (
      <div className="warn">
        {US_ONLY} <span className="dim">(NON-US LISTINGS, INDICES, FX, FUNDS WITHOUT 10-K/10-Q{error.detail ? ` · ${error.detail}` : ""})</span>
      </div>
    );
  const down = error.status !== 0 && error.kind === "unavailable";
  return (
    <div className="err">
      {down ? `PROVIDER DOWN: ${error.message}` : error.message}
      {error.detail && <span className="dim"> ({error.detail})</span>}
      {hasData && <span className="warn"> · SHOWING STALE DATA · F5 RETRY</span>}
      {error.kind === "bad_request" && usage && <span className="dim"> · USAGE: {usage}</span>}
      {SEC_UA_RE.test(error.detail ?? "") && <div className="warn">{SEC_UA_HINT}</div>}
    </div>
  );
}
