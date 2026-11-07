/**
 * PORTS: daily activity at about 1,600 ports from IMF PortWatch (satellite ship signals, published weekly).
 * `PORTS` = the 25 busiest ports of the last 7 days on record; `PORTS <port or country words>` (PORTS rotterdam, PORTS japan,
 * PORTS port said) = the biggest 20 ports whose name or country contains every word. The data service allows 1000 rows per call,
 * so the panel never loads all ports; that is why a search is needed to reach a smaller port.
 * Every row carries its own date (the newest day is usually 6 to 12 days old). 7D = average port calls per day over the last 7 days
 * on record; VS 21D = change against the 21 days before. IMP / EXP = PortWatch's own modelled daily trade estimates, averaged over
 * the same 7 days (not measured cargo). A traffic count, not a price and not a forecast. Keys: arrows move, E CSV, F5 refresh.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { registerPanelKeys } from "../keys/panelKeys";
import { usePanelRefresh } from "./panelRefresh";
import { mapArgsFor, openMap } from "../map/jump";
import { ApiError } from "../net/core";
import type { Envelope, PortRow, PortsPayload } from "../net/types";
import { worldApi } from "../net/worldApi";
import { EnvStatus, ErrorLine } from "./panelStatus";
import { fmtTons, headline, portLabel, queryArg } from "./portsFormat";
import { navKey } from "../keys/gridNav";
import { useLatest } from "../state/useLatest";
import type { FunctionProps } from "./registry";
import { chgColor, fmtPct, fmtShips, spark } from "./shipFormat";
import { gridCsv, useCsvExport } from "./tableExport";

const COLUMNS: Column<PortRow>[] = [
  { title: "PORT", width: 20, text: (r) => r.name, color: () => "acc" },
  { title: "COUNTRY", width: 16, text: (r) => r.country ?? "" },
  { title: "7D CALLS", width: 8, align: "right", text: (r) => fmtShips(r.avg7) },
  { title: "VS 21D", width: 8, align: "right", text: (r) => fmtPct(r.chg_pct), color: (r) => chgColor(r.chg_pct) },
  { title: "TANKER", width: 7, align: "right", text: (r) => fmtShips(r.tanker) },
  { title: "CONT.", width: 7, align: "right", text: (r) => fmtShips(r.container) },
  { title: "DRY BULK", width: 8, align: "right", text: (r) => fmtShips(r.dry_bulk) },
  { title: "IMP/DAY", width: 8, align: "right", text: (r) => fmtTons(r.imp7) },
  { title: "EXP/DAY", width: 8, align: "right", text: (r) => fmtTons(r.exp7) },
  { title: "28 DAYS", width: 28, text: (r) => spark(r.series), color: () => "dim" },
  { title: "LAST DAY", width: 14, text: (r) => r.date + (r.stale ? " STALE" : ""), color: (r) => (r.stale ? "warn" : "dim") },
];

export default function PORTS({ panelId, args }: FunctionProps) {
  const query = useMemo(() => queryArg(args), [args]);
  const [env, setEnv] = useState<Envelope<PortsPayload> | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [sel, setSel] = useState(0);
  const grid = useRef<GridHandle>(null);

  const load = useCallback(
    (fresh: boolean) => {
      setLoading(true);
      return worldApi
        .ports(query, fresh)
        .then((e) => {
          setEnv(e);
          setError(null);
        })
        .catch((e: ApiError) => {
          setEnv(null); // another search's rows must not stay on screen under this search's error
          setError(e);
        })
        .finally(() => setLoading(false));
    },
    [query],
  );

  useEffect(() => {
    void load(false);
  }, [load]);

  const d = env?.data;
  const rows = useMemo(() => d?.rows ?? [], [d]);
  const latest = useLatest({ rows });
  useCsvExport(panelId, () =>
    d
      ? gridCsv(
          "PORTS",
          [
            { title: "ID", width: 14, text: (r: PortRow) => r.id },
            ...COLUMNS,
            { title: "LAT", width: 9, text: (r: PortRow) => (r.lat == null ? "" : r.lat.toFixed(3)) },
            { title: "LON", width: 9, text: (r: PortRow) => (r.lon == null ? "" : r.lon.toFixed(3)) },
          ],
          rows,
        )
      : null,
  );

  usePanelRefresh(panelId, () => { void load(true); });
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        if (navKey(e, grid.current, latest.current.rows.length)) return true;
        if (e.key === "m") {
          openMap(panelId, mapArgsFor("PORTS")!); // M = the busiest ports on the map
          return true;
        }
        return false;
      }),
    [panelId, latest],
  );

  const cur = rows[sel];
  return (
    <div className="fn">
      <div className="line">
        <span className="acc">PORTS</span> {d ? headline(d.mode, d.query, rows.length) : "PORT ACTIVITY"}
        <EnvStatus env={env} loading={loading} />
        <span className="dim"> · M MAP · E CSV · F5 REFRESH{d?.mode === "top" ? " · PORTS <PORT OR COUNTRY> TO SEARCH" : ""}</span>
      </div>
      {d && <div className="dim">NEWEST DAY ON RECORD {d.newest}. {d.note}</div>}
      <ErrorLine error={error} hasData={!!d} usage="PORTS [PORT OR COUNTRY]" />
      {d && d.no_daily_rows > 0 && <div className="warn">{d.no_daily_rows} MORE MATCHING PORT(S) HAVE NO DAILY DATA AND ARE NOT SHOWN</div>}
      {cur && (
        <div className="line">
          <span className="acc">{portLabel(cur.name, cur.country).toUpperCase()}</span> · LAST DAY {cur.last ?? "?"} CALLS · 7D {fmtShips(cur.avg7)} VS 21D BEFORE {fmtShips(cur.base)}
          {cur.lat != null && cur.lon != null && <span className="dim"> · {cur.lat.toFixed(2)}, {cur.lon.toFixed(2)}</span>}
          {cur.base_days < 21 && <span className="warn"> · ONLY {cur.base_days} DAYS OF BASE, CHANGE UNRELIABLE</span>}
        </div>
      )}
      <Grid ref={grid} columns={COLUMNS} rows={rows} onSelect={setSel} />
    </div>
  );
}
