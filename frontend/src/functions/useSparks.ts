/**
 * The board's 2DAY sparkline data: closes of the last two sessions per symbol, from ONE batched request (`/api/sparks`).
 * Loaded after (and apart from) the quotes, so a slow or failed sparkline call never delays or breaks the numbers.
 * A symbol the source sent no points for is simply absent: its cell stays blank (never a made-up line).
 */
import { useEffect, useState } from "react";
import { ApiError } from "../net/core";
import { marketApi } from "../net/marketApi";

export interface Sparks {
  /** symbol (as requested) -> closes in time order. */
  by: Record<string, number[]>;
  /** Set when the request failed: the board says so in its first line and the cells stay blank. */
  error: string | null;
}

const NONE: Sparks = { by: {}, error: null };

export function useSparks(inputs: string[], reload: number): Sparks {
  const [sparks, setSparks] = useState<Sparks>(NONE);
  useEffect(() => {
    let alive = true;
    // `reload` > 0 is F5 or the retry button: skip the client's short cache.
    marketApi
      .sparks(inputs, reload > 0)
      .then((env) => alive && setSparks({ by: env.data, error: null }))
      .catch((e: ApiError) => alive && setSparks({ by: {}, error: e.message }));
    return () => {
      alive = false;
    };
  }, [inputs, reload]);
  return sparks;
}
