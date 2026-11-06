/**
 * CENB: central bank calendar. Policy rate (Fed, ECB, Bank of England, Bank of Canada from keyless sources) and rate-decision dates of eight banks.
 * Dates are a DATED TABLE transcribed from each bank's schedule page (the Fed's come live from federalreserve.gov); a bank/year not in the table says
 * CALENDAR NOT LOADED, never an estimate. Enter lists the bank's dates, E exports CSV, F5 refreshes.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { registerPanelKeys } from "../keys/panelKeys";
import { usePanelRefresh } from "./panelRefresh";
import { ApiError } from "../net/core";
import type { CenbPayload, CenbRow, Envelope } from "../net/types";
import { worldApi } from "../net/worldApi";
import { EnvStatus, ErrorLine } from "./macroUi";
import { navKey } from "../keys/gridNav";
import { useLatest } from "../state/useLatest";
import type { FunctionProps } from "./registry";
import { gridCsv, useCsvExport } from "./tableExport";

const rate = (r: CenbRow) => (r.rate == null ? "" : `${r.rate.toFixed(2)}%`);

export default function CENB({ panelId }: FunctionProps) {
  const [env, setEnv] = useState<Envelope<CenbPayload> | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [detail, setDetail] = useState<string | null>(null);
  const grid = useRef<GridHandle>(null);

  const load = useCallback((fresh: boolean) => {
    setLoading(true);
    return worldApi
      .cenb(fresh)
      .then((e) => {
        setEnv(e);
        setError(null);
      })
      .catch((e: ApiError) => setError(e))
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => {
    void load(false);
  }, [load]);

  const d = env?.data;
  const rows = useMemo(() => d?.rows ?? [], [d]);
  const latest = useLatest(rows);
  const columns = useMemo<Column<CenbRow>[]>(
    () => [
      { title: "BANK", width: 5, text: (r) => r.bank, color: () => "acc" },
      { title: "NAME", width: 27, text: (r) => r.name },
      { title: "RATE", width: 7, align: "right", text: rate },
      { title: "RATE AS OF", width: 11, text: (r) => r.rate_as_of ?? "", color: () => "dim" },
      { title: "LAST", width: 11, text: (r) => r.last ?? "", color: () => "dim" },
      { title: "NEXT", width: 11, text: (r) => r.next ?? "", color: (r) => (r.days != null && r.days <= 7 ? "warn" : "fg") },
      { title: "DAYS", width: 5, align: "right", text: (r) => (r.days == null ? "" : String(r.days)) },
      { title: "THEN", width: 11, text: (r) => r.after ?? "", color: () => "dim" },
      { title: "NOTE", width: 60, text: (r) => r.note ?? (r.rate == null ? (r.rate_note ?? "") : ""), color: () => "warn" },
    ],
    [],
  );
  useCsvExport(panelId, () => (d ? gridCsv("CENB", columns, rows) : null));

  usePanelRefresh(panelId, () => { void load(true); });
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        if (e.ctrlKey || e.altKey || e.metaKey) return false;
        const g = grid.current;
        const cur = latest.current;
        if (navKey(e, g, cur.length)) return true;
        if (e.key === "Enter") {
          const r = cur[g?.selected() ?? -1];
          setDetail(r ? `${r.bank} DECISIONS: ${r.dates.length ? r.dates.join(" ") : "NONE LOADED"} · SOURCE ${r.url}` : null);
          return true;
        }
        return false;
      }),
    [panelId, latest],
  );

  return (
    <div className="fn">
      <div className="line">
        <span className="acc">CENB</span> CENTRAL BANKS · {rows.length}
        {d && <span className="dim"> · TODAY {d.today} · CALENDAR TABLE AS OF {d.calendar_as_of}</span>}
        <EnvStatus env={env} loading={loading} />
        <span className="dim legend"> · J/K MOVE · ENTER DATES · E CSV · F5 REFRESH</span>
      </div>
      {d && <div className="dim">{d.note}. RATES: FED = TARGET UPPER BOUND (FRED), ECB = MAIN REFINANCING RATE, BOE = BANK RATE, BOC = OVERNIGHT TARGET. OTHER BANKS HAVE NO KEYLESS RATE SOURCE.</div>}
      {d?.notes.map((n) => <div key={n} className="warn">{n}</div>)}
      <ErrorLine error={error} hasData={!!d} usage="CENB" />
      {detail && <div className="line">{detail}</div>}
      <Grid ref={grid} columns={columns} rows={rows} />
    </div>
  );
}
