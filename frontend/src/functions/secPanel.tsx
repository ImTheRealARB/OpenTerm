/** Shared bits of the Phase 6 panels (FA, FIL, OWN, HDS): envelope loading and the header/error lines. */
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { fmtAge } from "../format";
import type { ApiError, Envelope } from "../net/api";

export const US_ONLY = "SEC DATA COVERS US FILERS ONLY";

const SOURCE_NAMES: Record<string, string> = { sec: "SEC EDGAR", yahoo_own: "YAHOO FINANCE", fixtures: "FIXTURES" };
export const sourceName = (s: string | null | undefined) => SOURCE_NAMES[s ?? ""] ?? (s ?? "").toUpperCase();

/** Loads one envelope per `key`; a late answer for an old key is dropped. `reload(true)` is F5. */
export function useEnvelope<T>(key: string, load: (fresh: boolean) => Promise<Envelope<T>>) {
  const [env, setEnv] = useState<Envelope<T> | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const current = useRef(key);
  const loader = useRef(load);
  loader.current = load;

  const reload = useCallback(
    (fresh: boolean) => {
      const k = key;
      setLoading(true);
      return loader
        .current(fresh)
        .then((e) => {
          if (current.current !== k) return;
          setEnv(e);
          setError(null);
        })
        .catch((e: ApiError) => {
          if (current.current === k) setError(e);
        })
        .finally(() => {
          if (current.current === k) setLoading(false);
        });
    },
    [key],
  );

  useEffect(() => {
    current.current = key;
    setEnv(null);
    setError(null);
    void reload(false);
  }, [key, reload]);

  return { env, error, loading, reload };
}

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
      <span className="dim"> · {keys}</span>
    </div>
  );
}

/** Error line. "US filers only" is a coverage state, not a failure, so it is shown in the warning colour. */
export function ErrorLine({ error, hasData }: { error: ApiError | null; hasData: boolean }) {
  if (!error) return null;
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
      {/SEC_USER_AGENT|403 from SEC/.test(error.detail ?? "") && (
        <div className="warn">SEC REJECTED THE REQUEST: SET SEC_USER_AGENT="Your Name you@yourdomain" IN .env AND RESTART THE BACKEND</div>
      )}
    </div>
  );
}

export function openUrl(url: string): void {
  // SEC pages open on sec.gov in a new tab; nothing is scraped or shown here.
  window.open(url, "_blank", "noopener,noreferrer");
}
