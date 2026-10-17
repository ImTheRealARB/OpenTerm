/** Shared status pieces for the Phase 7 macro panels: source + age, STALE, fallback, and the error line. */
import { fmtAge } from "../format";
import type { ApiError, Envelope } from "../net/api";

export function EnvStatus({ env, loading }: { env: Envelope<unknown> | null; loading: boolean }) {
  return (
    <>
      {env && ` · ${(env.source ?? "").toUpperCase()}`}
      {env && <span className={env.stale ? "warn" : "dim"}> · {env.stale ? "STALE " : "AGE "}{fmtAge(env.age_s)}</span>}
      {env && env.fallback_from.length > 0 && <span className="warn"> · {env.fallback_from.join(",").toUpperCase()} DOWN, VIA FALLBACK</span>}
      {loading && <span className="dim"> · LOADING…</span>}
    </>
  );
}

/** A failed load. When older data is still on screen it is said to be STALE rather than hidden. */
export function ErrorLine({ error, hasData, usage }: { error: ApiError | null; hasData: boolean; usage?: string }) {
  if (!error) return null;
  const down = error.status !== 0 && error.kind === "unavailable";
  return (
    <div className="err">
      {down ? `PROVIDER DOWN: ${error.message}` : error.message}
      {error.detail && <span className="dim"> ({error.detail})</span>}
      {hasData && <span className="warn"> · SHOWING STALE DATA · F5 RETRY</span>}
      {error.kind === "bad_request" && usage && <span className="dim"> · USAGE: {usage}</span>}
    </div>
  );
}
