/**
 * Today's % change for a list of symbols, fetched in the background and kept (IMAP ETF colours its tiles with it).
 *
 * Only symbols not seen yet are asked for, in chunks, after a short pause: while the ETF table is still loading the "biggest 150
 * funds" list changes every few seconds, and asking for all of it each time would hammer the quote source for nothing.
 * A symbol the quote source has no answer for is kept as `null` (so it is not asked again until F5), never as a made-up number.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import type { ApiError } from "../net/core";
import { marketApi } from "../net/marketApi";
import { useLatest } from "../state/useLatest";

const CHUNK = 100; // symbols per request (the quote URL stays short)
const PAUSE_MS = 1_500; // wait this long after the list last changed

export function useQuotePct(symbols: string[]) {
  const [pct, setPct] = useState<ReadonlyMap<string, number | null>>(new Map());
  const [error, setError] = useState<ApiError | null>(null);
  const [epoch, setEpoch] = useState(0); // F5 bumps it: forget everything and ask again
  const held = useRef(new Map<string, number | null>());
  const latest = useLatest(symbols);
  const key = symbols.join(",");

  useEffect(() => {
    const missing = latest.current.filter((s) => !held.current.has(s));
    if (!missing.length) return;
    let alive = true;
    const timer = window.setTimeout(async () => {
      for (let i = 0; i < missing.length && alive; i += CHUNK) {
        try {
          const { results } = await marketApi.quotes(missing.slice(i, i + CHUNK));
          if (!alive) return;
          for (const s of missing.slice(i, i + CHUNK)) {
            const r = results[s];
            held.current.set(s, r && "data" in r ? r.data.change_pct : null);
          }
          setPct(new Map(held.current));
          setError(null);
        } catch (e) {
          if (alive) setError(e as ApiError); // shown by the panel; these symbols are asked for again on the next change or F5
          return;
        }
      }
    }, PAUSE_MS);
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [key, epoch, latest]);

  /** Forget every quote and ask again (the panel's refresh key). */
  const reload = useCallback(() => {
    held.current = new Map();
    setPct(new Map());
    setEpoch((n) => n + 1);
  }, []);
  return { pct, error, reload };
}
