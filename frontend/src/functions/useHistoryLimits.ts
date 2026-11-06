import { useEffect, useState } from "react";
import { marketApi } from "../net/marketApi";
import type { IntradayLimits } from "./gpArgs";

/**
 * How far back each minute candle length reaches for a symbol, from the backend (the deepest source that is switched on for it).
 *
 * It is only a hint for the candle-length dropdown: while it loads, or if the request fails, it is `undefined` and the dropdown
 * offers everything; the server's own error stays the authority. (Kept out of gpArgs.ts because that file must stay free of
 * `net/core` so vitest can import it.)
 */
export function useHistoryLimits(symbol: string | undefined): IntradayLimits | undefined {
  const [limits, setLimits] = useState<{ symbol: string; days: IntradayLimits } | undefined>();
  useEffect(() => {
    if (!symbol) return;
    let alive = true;
    marketApi
      .historyLimits(symbol)
      .then((r) => {
        if (alive) setLimits({ symbol, days: r.intraday_days });
      })
      .catch(() => {
        // A hint only: no hint is the safe answer.
      });
    return () => {
      alive = false;
    };
  }, [symbol]);
  return limits && limits.symbol === symbol ? limits.days : undefined;
}
