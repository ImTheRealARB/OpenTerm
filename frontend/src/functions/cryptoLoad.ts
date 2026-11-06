/** Shared load state for the crypto depth panels (CDEP, FUND, LIQ, STBL, DEFI): envelope, error, loading, optional auto refresh. */
import { useCallback, useEffect, useState } from "react";
import type { ApiError, Envelope } from "../net/api";

export function useEnvLoad<T>(fetcher: (fresh: boolean) => Promise<Envelope<T>>, key: string, refreshMs = 0) {
  const [env, setEnv] = useState<Envelope<T> | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);

  // `key` names what `fetcher` reads (pair, symbol, query): a new key is a new load.
  const load = useCallback(
    (fresh: boolean) => {
      setLoading(true);
      return fetcher(fresh)
        .then((e) => {
          setEnv(e);
          setError(null);
        })
        .catch((e: ApiError) => setError(e))
        .finally(() => setLoading(false));
    },
    // Callers pass an inline fetcher (new function every render); depending on it would reload on every render, forever.
    // eslint-disable-next-line react-hooks/exhaustive-deps -- key names what fetcher reads; a new key is the only reason to reload
    [key],
  );

  useEffect(() => {
    setEnv(null);
    void load(false);
    if (!refreshMs) return;
    const t = setInterval(() => void load(true), refreshMs);
    return () => clearInterval(t);
  }, [load, refreshMs]);

  return { env, error, loading, load };
}
