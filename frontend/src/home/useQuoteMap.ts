/**
 * One REST snapshot + one WebSocket subscription for a list of symbols, as a lookup by symbol.
 * HOME asks once for the tape's symbols plus every block's; the global tape bar asks for the tape's alone. `subscribe` is
 * reference-counted (net/socket.ts), so a symbol both want is still subscribed once.
 * The snapshot repeats every `movers` poll interval; ticks between snapshots go straight to the DOM (liveCells.tsx).
 */
import { useEffect, useMemo, useState } from "react";
import { useQuotes, type QRow } from "../functions/quoteRows";
import { subscribe } from "../net/socket";
import { pollMs } from "../settings/runtime";

export function useQuoteMap(symbols: readonly string[]): Map<string, QRow> {
  // A stable array while the symbols are unchanged (useQuotes refetches when its `inputs` identity changes).
  const key = symbols.join(",");
  const inputs = useMemo(() => (key ? key.split(",") : []), [key]);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setReload((n) => n + 1), pollMs("movers"));
    return () => clearInterval(t);
  }, []);
  const { rows } = useQuotes(inputs, reload);
  useEffect(() => (inputs.length ? subscribe(inputs) : undefined), [inputs]);
  return useMemo(() => new Map(rows.map((r) => [r.input, r])), [rows]);
}
