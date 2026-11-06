/**
 * The one hook that loads an API envelope (data + source + age) for a panel, shared by every "fetch by key" panel
 * (FA, FIL, OWN, HDS, ECO, MACRO, N, CRYP, HIST, ResearchPanel and the world panels CDEP, FUND, LIQ, STBL, DEFI, ADDR, UKCO...).
 *
 * `key` names what `load` reads (a symbol, a query, a page). A new key is a new load: the old data is cleared and the
 * fetch starts. If an answer for an OLD key arrives after the key changed it is dropped (otherwise a slow request for
 * the previous symbol would overwrite the current one: the bug the old crypto-only copy of this hook had).
 *
 * `refreshMs` > 0 also refetches (fresh) on that interval. `reload(true)` is the panel's refresh key.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import type { ApiError } from "../net/core";
import type { Envelope } from "../net/types";
import { keyGate } from "./keyedLoad";

export function useEnvelope<T>(key: string, load: (fresh: boolean) => Promise<Envelope<T>>, refreshMs = 0) {
  const [env, setEnv] = useState<Envelope<T> | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  // Which key the panel shows right now; answers asked for any other key are ignored.
  const gate = useRef(keyGate(key));
  // Callers pass an inline `load` (a new function every render). Reading it through a ref means we always call the
  // latest one without reloading on every render.
  const loader = useRef(load);
  loader.current = load;

  const reload = useCallback(
    (fresh: boolean) => {
      const asked = key;
      setLoading(true);
      return loader
        .current(fresh)
        .then((e) => {
          if (!gate.current.isCurrent(asked)) return;
          setEnv(e);
          setError(null);
        })
        .catch((e: ApiError) => {
          if (gate.current.isCurrent(asked)) setError(e);
        })
        .finally(() => {
          if (gate.current.isCurrent(asked)) setLoading(false);
        });
    },
    [key],
  );

  // A new key: forget the old data and load the new thing.
  useEffect(() => {
    gate.current.set(key);
    setEnv(null);
    setError(null);
    void reload(false);
  }, [key, reload]);

  // Optional auto refresh. It restarts when the key changes, so it never polls an old key.
  useEffect(() => {
    if (!refreshMs) return;
    const t = setInterval(() => void reload(true), refreshMs);
    return () => clearInterval(t);
  }, [reload, refreshMs]);

  return { env, error, loading, reload };
}
