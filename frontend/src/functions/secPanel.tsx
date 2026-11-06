/** Shared bits of the Phase 6 panels (FA, FIL, OWN, HDS): envelope loading and the header/error lines. */
import type { ReactNode } from "react";
import { fmtAge } from "../format";
import type { ApiError } from "../net/core";
import type { Envelope } from "../net/types";
import { isKeyRequired, KeyRequiredLine } from "./KeyRequiredLine";

export const US_ONLY = "SEC DATA COVERS US FILERS ONLY";
/** SEC answers 403 when no contact User-Agent is set: the error detail mentions it, and the fix is the same everywhere. */
export const SEC_UA_RE = /SEC_USER_AGENT|403 from SEC/;
export const SEC_UA_HINT = 'SEC REJECTED THE REQUEST: SET SEC_USER_AGENT="Your Name you@yourdomain" IN .env AND RESTART THE BACKEND';

const SOURCE_NAMES: Record<string, string> = { sec: "SEC EDGAR", yahoo_own: "YAHOO FINANCE", fixtures: "FIXTURES" };
export const sourceName = (s: string | null | undefined) => SOURCE_NAMES[s ?? ""] ?? (s ?? "").toUpperCase();

// The shared envelope loader lives in useEnvelope.ts; re-exported here so the SEC panels keep one import line.
export { useEnvelope } from "./useEnvelope";

/** Title line: name, source, staleness and the panel's key hints. */
export function Header({ title, env, loading, extra, keys }: { title: ReactNode; env: Envelope<unknown> | null; loading: boolean; extra?: ReactNode; keys: string }) {
  return (
    <div className="line">
      <span className="acc">{title}</span>
      {env && ` · ${sourceName(env.source)}`}
      {env && env.fallback_from.length > 0 && <span className="warn"> · FALLBACK FROM {env.fallback_from.join(", ").toUpperCase()}</span>}
      {env?.stale && <span className="warn"> · STALE {fmtAge(env.age_s)}</span>}
      {extra}
      {loading && <span className="dim"> · LOADING…</span>}
      <span className="dim legend"> · {keys}</span>
    </div>
  );
}

/** Error line. "US filers only" is a coverage state, not a failure, so it is shown in the warning colour. */
export function ErrorLine({ error, hasData }: { error: ApiError | null; hasData: boolean }) {
  if (!error) return null;
  if (isKeyRequired(error)) return <KeyRequiredLine error={error} />;
  if (error.message === US_ONLY)
    return (
      <div className="warn">
        {US_ONLY} <span className="dim">(NON-US LISTINGS, INDICES, FX, FUNDS WITHOUT 10-K/10-Q{error.detail ? ` · ${error.detail}` : ""})</span>
      </div>
    );
  return (
    <div className="err">
      {error.message}
      {error.detail && <span className="dim"> ({error.detail})</span>}
      {hasData && <span className="warn"> · SHOWING THE LAST DATA</span>}
      {SEC_UA_RE.test(error.detail ?? "") && <div className="warn">{SEC_UA_HINT}</div>}
    </div>
  );
}

export function openUrl(url: string): void {
  // SEC pages open on sec.gov in a new tab; nothing is scraped or shown here.
  window.open(url, "_blank", "noopener,noreferrer");
}
