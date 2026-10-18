/**
 * NRG: the energy board. Crude, natural gas, refined products and retail fuel from FRED's keyless CSV (series FRED republishes from EIA).
 * Prices only: EIA's weekly stocks and production are not on that feed. `NRG <series>` opens the series on the FRED chart; Enter does the same
 * for the selected row. Yellow = the last value is older than its normal lag. Keys: Enter FRED, E CSV, F5 refresh.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { registerPanelKeys } from "../keys/panelKeys";
import { ApiError, worldApi, type Envelope, type NrgPayload, type NrgRow } from "../net/api";
import { navigate } from "../state/workspace";
import { fmtPrice, fmtSigned, nrgChg, parseNrgArgs, posBar } from "./energyArgs";
import { EnvStatus, ErrorLine } from "./macroUi";
import { navKey, useLatest } from "./quoteRows";
import type { FunctionProps } from "./registry";
import { gridCsv, useCsvExport } from "./tableExport";

const COLUMNS: Column<NrgRow>[] = [
  { title: "SERIES", width: 10, text: (r) => r.alias, color: () => "acc" },
  { title: "NAME", width: 37, text: (r) => r.label },
  { title: "LAST", width: 9, align: "right", text: (r) => (r.error ? "ERR" : fmtPrice(r.last, r.unit)), color: (r) => (r.error ? "err" : r.stale ? "warn" : "fg") },
  { title: "UNIT", width: 8, text: (r) => r.unit, color: () => "dim" },
  { title: "CHG", width: 8, align: "right", text: (r) => fmtSigned(r.chg, r.unit === "$/GAL" || r.unit === "$/MMBTU" ? 3 : 2), color: (r) => nrgChg(r) },
  { title: "CHG%", width: 7, align: "right", text: (r) => (r.pct == null ? "" : fmtSigned(r.pct, 2) + "%"), color: (r) => nrgChg(r) },
  { title: "1Y LOW", width: 8, align: "right", text: (r) => fmtPrice(r.lo, r.unit) },
  { title: "1Y HIGH", width: 8, align: "right", text: (r) => fmtPrice(r.hi, r.unit) },
  { title: "1Y RANGE", width: 10, text: (r) => posBar(r.pos), color: () => "dim" },
  { title: "AS OF", width: 11, text: (r) => (r.error ? r.error.slice(0, 30) : (r.date ?? "") + (r.stale ? " STALE" : "")), color: (r) => (r.error ? "err" : r.stale ? "warn" : "dim") },
];

export default function NRG({ panelId, args }: FunctionProps) {
  const p = useMemo(() => parseNrgArgs(args), [args]);
  const [env, setEnv] = useState<Envelope<NrgPayload> | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const grid = useRef<GridHandle>(null);

  const load = useCallback((fresh: boolean) => {
    setLoading(true);
    return worldApi
      .nrg(fresh)
      .then((e) => {
        setEnv(e);
        setError(null);
      })
      .catch((e: ApiError) => setError(e))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (p.id) navigate(panelId, { fn: "FRED", args: [p.id], security: undefined });
    else if (!p.error) void load(false);
  }, [p.id, p.error, panelId, load]);

  const d = env?.data;
  const rows = useMemo(() => d?.rows ?? [], [d]);
  const latest = useLatest({ rows });
  useCsvExport(panelId, () => (d ? gridCsv("NRG", [{ title: "FRED ID", width: 14, text: (r: NrgRow) => r.id }, ...COLUMNS], rows) : null));

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        if (e.ctrlKey || e.altKey || e.metaKey) return false;
        const g = grid.current;
        const cur = latest.current;
        if (navKey(e, g, cur.rows.length)) return true;
        if (e.key === "F5") {
          void load(true);
          return true;
        }
        if (e.key === "Enter") {
          const r = cur.rows[g?.selected() ?? -1];
          if (r) navigate(panelId, { fn: "FRED", args: [r.id], security: undefined });
          return true;
        }
        return false;
      }),
    [panelId, latest, load],
  );

  if (p.error) {
    return (
      <div className="fn">
        <div className="line"><span className="acc">NRG</span> · {p.error}</div>
        <div className="dim">NRG = THE BOARD · NRG WTI OPENS THE SERIES ON FRED</div>
      </div>
    );
  }
  return (
    <div className="fn">
      <div className="line">
        <span className="acc">NRG</span> ENERGY · {rows.length} SERIES
        <EnvStatus env={env} loading={loading} />
        <span className="dim"> · ENTER OPEN ON FRED · E CSV · F5 REFRESH</span>
      </div>
      {d?.spread && (
        <div className="line">
          {d.spread.label} <span className="acc">{d.spread.value.toFixed(2)}</span> {d.spread.unit} <span className="dim">({d.spread.date})</span>
        </div>
      )}
      {d && <div className="dim">SOURCE: {(env?.source ?? "").toUpperCase()}. {d.note} YELLOW = OLDER THAN NORMAL LAG.</div>}
      {d && d.failed.length > 0 && <div className="warn">{d.failed.join(", ")} DID NOT ANSWER: ERR BELOW. F5 RETRIES.</div>}
      <ErrorLine error={error} hasData={!!d} usage="NRG" />
      <Grid ref={grid} columns={COLUMNS} rows={rows} />
    </div>
  );
}
