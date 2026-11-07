/** FRED series browser. Keyless: a built-in list of well-known series with latest values. With FRED_API_KEY: search all of FRED. */
import { useEffect, useMemo, useRef } from "react";
import { prefillCommand } from "../components/CommandLine";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { registerPanelKeys } from "../keys/panelKeys";
import { usePanelRefresh } from "./panelRefresh";
import { macroApi } from "../net/macroApi";
import type { MacroPayload, MacroRow } from "../net/types";
import { navigate } from "../state/workspace";
import { fmtSeriesChange, fmtSeriesValue, parseMacroArgs } from "./macroArgs";
import { EnvStatus, ErrorLine } from "./panelStatus";
import { dirColor } from "./quoteRows";
import { navKey } from "../keys/gridNav";
import { useLatest } from "../state/useLatest";
import type { FunctionProps } from "./registry";
import { useEnvelope } from "./secPanel";
import { gridCsv, useCsvExport } from "./tableExport";

const POLL_MS = 300_000;

const COLUMNS: Column<MacroRow>[] = [
  { title: "SERIES", width: 16, text: (r) => r.id, color: () => "acc" },
  { title: "NAME", width: 30, text: (r) => r.label ?? r.title ?? "" },
  { title: "LAST", width: 12, align: "right", text: (r) => (r.error ? "ERR" : fmtSeriesValue(r.last_value)), color: (r) => (r.error ? "err" : "fg") },
  { title: "CHG", width: 10, align: "right", text: (r) => (r.error ? "" : fmtSeriesChange(r.change)), color: (r) => dirColor(r.change ?? null) },
  { title: "AS OF", width: 10, text: (r) => r.last_date ?? r.observation_end ?? "", color: () => "dim" },
  { title: "FREQ", width: 10, text: (r) => r.frequency ?? "", color: () => "dim" },
  { title: "UNITS / NOTE", width: 40, text: (r) => r.error ?? r.units ?? "", color: (r) => (r.error ? "err" : "dim") },
];

export default function MACRO({ panelId, args }: FunctionProps) {
  const q = useMemo(() => parseMacroArgs(args), [args]);
  const grid = useRef<GridHandle>(null);

  const { env, error, loading, reload: load } = useEnvelope<MacroPayload>(JSON.stringify(q), (fresh) => macroApi.macro(q, fresh));

  useEffect(() => {
    const t = setInterval(() => void load(false), POLL_MS);
    return () => clearInterval(t);
  }, [load]);

  const rows = useMemo(() => env?.data.rows ?? [], [env]);
  const latest = useLatest(rows);
  useCsvExport(panelId, () => gridCsv("MACRO", COLUMNS, rows));

  usePanelRefresh(panelId, () => { void load(true); });
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const g = grid.current;
        const cur = latest.current;
        if (navKey(e, g, cur.length)) return true;
        switch (e.key) {
          case "Enter": {
            const r = cur[g?.selected() ?? -1];
            if (r) navigate(panelId, { fn: "FRED", security: undefined, args: [r.id] });
            return true;
          }
          case "s":
          case "/":
            prefillCommand("MACRO ");
            return true;
        }
        return false;
      }),
    [panelId, latest],
  );

  const d = env?.data;
  return (
    <div className="fn">
      <div className="line">
        <span className="acc">MACRO</span> · {d?.mode === "search" ? `FRED SEARCH "${d.query}"` : q ? `BUILT-IN LIST MATCHING "${q.toUpperCase()}"` : "COMMON FRED SERIES"}
        {d && ` · ${rows.length} SERIES`}
        <EnvStatus env={env} loading={loading} />
        <span className="dim legend"> · J/K MOVE · ENTER PLOT (FRED) · S SEARCH · E CSV · F5 REFRESH</span>
      </div>
      {d?.needs_key && (
        <div className="warn">
          SEARCH OF ALL FRED NEEDS {d.needs_key} (FREE AT FRED.STLOUISFED.ORG, THEN ADD IT TO .env). LIST BELOW IS THE BUILT-IN SET{q ? ", FILTERED LOCALLY" : ""}. FRED SERIES_ID PLOTS ANY ID.
        </div>
      )}
      {d && rows.length === 0 && !error && (
        <div className="dim">{d.needs_key ? `NO BUILT-IN SERIES MATCH "${q.toUpperCase()}". ` : ""}FRED SERIES_ID PLOTS ANY SERIES DIRECTLY.</div>
      )}
      <ErrorLine error={error} hasData={!!env} usage="MACRO [search text]" />
      <Grid ref={grid} columns={COLUMNS} rows={rows} />
    </div>
  );
}
