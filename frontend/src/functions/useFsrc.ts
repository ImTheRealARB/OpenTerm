/**
 * Loads the ETF table for FSRC and for IMAP ETF. The server builds it slowly (about half an hour for every US ETF), so this hook
 * polls: each answer brings the rows added since the last one (`fsrcData.mergeFsrc`), and polling stops once the server says the
 * table is complete. Rows already held stay on screen while a later poll fails (the panel says so); the next poll tries again.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ApiError } from "../net/core";
import { etfApi } from "../net/etfApi";
import type { FsrcPayload, FsrcRow } from "../net/etfTypes";
import type { Envelope } from "../net/types";
import { FSRC_EMPTY, mergeFsrc, type FsrcHeld } from "./fsrcData";

const POLL_MS = 4_000; // while rows are still arriving (about 3 a second)
const PAUSED_MS = 10_000; // the server is waiting out a Yahoo rate limit: no point asking faster
const RETRY_MS = 15_000; // a failed poll (backend restarting, symbol list down)

export function useFsrc() {
  const [held, setHeld] = useState<FsrcHeld>(FSRC_EMPTY);
  const [env, setEnv] = useState<Envelope<FsrcPayload> | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const heldRef = useRef(FSRC_EMPTY); // what the next poll sends back (`run`, `seq`)
  const tickRef = useRef<() => void>(() => {});

  useEffect(() => {
    let alive = true;
    let timer: number | undefined;
    const tick = () => {
      window.clearTimeout(timer);
      setLoading(true);
      etfApi
        .screener(heldRef.current.run ?? undefined, heldRef.current.seq)
        .then((e) => {
          if (!alive) return;
          heldRef.current = mergeFsrc(heldRef.current, e.data);
          if (e.data.reset || e.data.rows.length) setHeld(heldRef.current); // nothing new (waiting on Yahoo): no re-render, no re-sort
          setEnv(e);
          setError(null);
          if (e.data.state !== "complete") timer = window.setTimeout(tick, e.data.state === "paused" ? PAUSED_MS : POLL_MS);
        })
        .catch((e: ApiError) => {
          if (!alive) return;
          setError(e); // shown by the panel; the rows already held stay visible, and we keep trying
          timer = window.setTimeout(tick, RETRY_MS);
        })
        .finally(() => {
          if (alive) setLoading(false);
        });
    };
    tickRef.current = tick;
    tick();
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, []);

  const rows = useMemo<FsrcRow[]>(() => [...held.rows.values()], [held]);
  /** The panel's refresh key: ask again now (it also restarts polling when the table was complete). */
  const reload = useCallback(() => tickRef.current(), []);
  return { rows, env, error, loading, reload };
}
