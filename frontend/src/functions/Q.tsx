import { useEffect, useMemo, useRef, useState } from "react";
import { commandInputRef } from "../components/CommandLine";
import { PanelNote } from "../components/PanelNote";
import { Grid, type GridHandle } from "../components/Grid";
import { registerPanelKeys } from "../keys/panelKeys";
import { navigate, replaceView } from "../state/workspace";
import { liveSymbol, navKey, QUOTE_COLUMNS, QUOTE_COLUMNS_GUI, SORTS, sortRows, useLatest, useLiveRows, useQuotes, type Sort } from "./quoteRows";
import { QuoteErrors } from "./QuoteErrors";
import { settingsStore } from "../settings/runtime";
import { useStore } from "../state/store";
import type { FunctionProps } from "./registry";
import { gridCsv, useCsvExport } from "./tableExport";

export const DEFAULT_LIST = ["SPY", "QQQ", "DIA", "^NSEI", "^BSESN", "AAPL", "MSFT", "RELIANCE.NS", "INFY.NS", "BTC-USD", "EURUSD=X", "GC=F", "CL=F"];

export default function Q({ panelId, args, security }: FunctionProps) {
  const inputs = useMemo(() => {
    const list = args.map((a) => a.toUpperCase()).filter(Boolean);
    if (list.length) return list;
    return security ? [security.symbol] : DEFAULT_LIST;
  }, [args, security]);
  const usingDefault = !args.length && !security;

  const gui = useStore(settingsStore, (st) => st.mode === "gui");
  const COLUMNS = gui ? QUOTE_COLUMNS_GUI : QUOTE_COLUMNS;
  const [reload, setReload] = useState(0);
  const { rows, setRows, loading } = useQuotes(inputs, reload);
  const [sort, setSort] = useState<Sort>("INPUT");
  const grid = useRef<GridHandle>(null);
  const latest = useLatest({ rows, sort });

  useLiveRows(rows, grid, liveSymbol);
  useCsvExport(panelId, () => gridCsv(`Q_${rows.map((r) => r.symbol).join("_").slice(0, 60)}`, COLUMNS, rows));

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const g = grid.current;
        const { rows: cur, sort: curSort } = latest.current;
        if (navKey(e, g, cur.length)) return true;
        const sel = g?.selected() ?? 0;
        switch (e.key) {
          case "Enter": {
            const r = cur[sel];
            if (r) navigate(panelId, { fn: "DES", security: { symbol: r.symbol }, args: [] });
            return true;
          }
          case "d": {
            if (!cur[sel]) return true;
            const next = cur.filter((_, i) => i !== sel).map((x) => x.input);
            replaceView(panelId, (v) => ({ ...v, args: next.length ? next : ["SPY"] }));
            return true;
          }
          case "a": {
            const el = commandInputRef.current;
            if (el) {
              el.focus();
              el.value = `${panelId}: Q ${cur.map((x) => x.input).join(" ")} `;
            }
            return true;
          }
          case "s": {
            const next = SORTS[(SORTS.indexOf(curSort) + 1) % SORTS.length];
            setSort(next);
            setRows(sortRows(cur, next, inputs));
            return true;
          }
          case "F5":
            setReload((n) => n + 1);
            return true;
        }
        return false;
      }),
    [panelId, inputs, latest, setRows],
  );

  return (
    <div className="fn">
      <div className="line">
        <span className="acc">QUOTE MONITOR</span> <b className="pv">{rows.length}</b> SECURITIES{usingDefault && " (DEFAULT LIST)"} · <span className="dim">SORT</span> {sort}
        {loading && <span className="dim"> · LOADING…</span>}
        <span className="dim legend"> · J/K MOVE · ENTER DES · A ADD · D DEL · S SORT · E CSV · F5 REFRESH</span>
      </div>
      {/* Only reachable if there are no inputs at all: say what to do instead of showing a blank grid. */}
      {!loading && rows.length === 0 && (
        <PanelNote kind="empty" hint="Type a ticker before Q, e.g. AAPL Q, or Q AAPL MSFT NVDA.">
          NO SECURITIES
        </PanelNote>
      )}
      <QuoteErrors rows={rows} onRetry={() => setReload((n) => n + 1)} />
      <Grid ref={grid} columns={COLUMNS} rows={rows} />
    </div>
  );
}
