/**
 * SHIP: ship traffic at 28 sea chokepoints (Suez, Panama, Hormuz, Malacca and so on) from IMF PortWatch.
 * Ships are counted from satellite radio (AIS) signals and published weekly, so the newest day is usually 8 to 12 days old:
 * every row carries its own date. 7D = average ships per day over the last 7 days on record; VS 21D = change against the
 * 21 days before. It is a traffic count, not a price and not a forecast. Keys: arrows move, E CSV, F5 refresh.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { registerPanelKeys } from "../keys/panelKeys";
import { usePanelRefresh } from "./panelRefresh";
import { mapArgsFor, openMap } from "../map/jump";
import { ApiError } from "../net/core";
import type { Envelope, ShipPayload, ShipRow } from "../net/types";
import { worldApi } from "../net/worldApi";
import { EnvStatus, ErrorLine } from "./panelStatus";
import { navKey } from "../keys/gridNav";
import { useLatest } from "../state/useLatest";
import type { FunctionProps } from "./registry";
import { chgColor, fmtPct, fmtShips, spark } from "./shipFormat";
import { gridCsv, useCsvExport } from "./tableExport";

const COLUMNS: Column<ShipRow>[] = [
  { title: "CHOKEPOINT", width: 22, text: (r) => r.name, color: () => "acc" },
  { title: "7D AVG", width: 7, align: "right", text: (r) => fmtShips(r.avg7) },
  { title: "VS 21D", width: 8, align: "right", text: (r) => fmtPct(r.chg_pct), color: (r) => chgColor(r.chg_pct) },
  { title: "TANKER", width: 7, align: "right", text: (r) => fmtShips(r.tanker) },
  { title: "CONT.", width: 7, align: "right", text: (r) => fmtShips(r.container) },
  { title: "DRY BULK", width: 8, align: "right", text: (r) => fmtShips(r.dry_bulk) },
  { title: "28 DAYS", width: 28, text: (r) => spark(r.series), color: () => "dim" },
  { title: "LAST DAY", width: 14, text: (r) => r.date + (r.stale ? " STALE" : ""), color: (r) => (r.stale ? "warn" : "dim") },
];

export default function SHIP({ panelId }: FunctionProps) {
  const [env, setEnv] = useState<Envelope<ShipPayload> | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [sel, setSel] = useState(0);
  const grid = useRef<GridHandle>(null);

  const load = useCallback((fresh: boolean) => {
    setLoading(true);
    return worldApi
      .ship(fresh)
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
  const latest = useLatest({ rows });
  useCsvExport(panelId, () => (d ? gridCsv("SHIP", [{ title: "ID", width: 14, text: (r: ShipRow) => r.id }, ...COLUMNS], rows) : null));

  usePanelRefresh(panelId, () => { void load(true); });
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        if (navKey(e, grid.current, latest.current.rows.length)) return true;
        if (e.key === "m") {
          openMap(panelId, mapArgsFor("SHIP")!); // M = the chokepoint boxes on the map
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
        <span className="acc">SHIP</span> CHOKEPOINT TRAFFIC · {rows.length} STRAITS AND CANALS
        <EnvStatus env={env} loading={loading} />
        <span className="dim"> · M MAP · E CSV · F5 REFRESH</span>
      </div>
      {d && <div className="dim">NEWEST DAY ON RECORD {d.newest}. {d.note}</div>}
      <ErrorLine error={error} hasData={!!d} usage="SHIP" />
      {cur && (
        <div className="line">
          <span className="acc">{cur.name.toUpperCase()}</span> · LAST DAY {cur.last ?? "?"} SHIPS · 7D {fmtShips(cur.avg7)} VS 21D BEFORE {fmtShips(cur.base)}
          {cur.base_days < 21 && <span className="warn"> · ONLY {cur.base_days} DAYS OF BASE, CHANGE UNRELIABLE</span>}
        </div>
      )}
      <Grid ref={grid} columns={COLUMNS} rows={rows} onSelect={setSel} />
    </div>
  );
}
