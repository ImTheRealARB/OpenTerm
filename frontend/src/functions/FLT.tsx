/**
 * FLT: live aircraft from the OpenSky Network (free; ADS-B positions collected by volunteer receivers).
 *   FLT LONDON | NYC | DUBAI | SINGAPORE | MUMBAI | BENGALURU | FRANKFURT     a small box over a city
 *   FLT BOX <SOUTH> <WEST> <NORTH> <EAST>                                      your own box (OpenSky charges credits by area, so it is capped)
 *   FLT CALLSIGN <PREFIX>                                                      aircraft whose callsign starts with it (a WHOLE-WORLD call, 4 credits)
 * Works with no account (anonymous: 400 credits a day). Adding OPENSKY_CLIENT_ID + OPENSKY_CLIENT_SECRET in APIKEYS raises that to 4000 a day.
 * Everything is AS REPORTED BY AIRCRAFT TRANSPONDERS: coverage is partial, and some aircraft do not appear or are filtered at the owner's request.
 * Altitude is shown in feet (the source speaks metres), speed in knots, climb in feet per minute; the CSV keeps the source units too.
 * Keys: arrows move, N / P next / previous city, E CSV, F5 refresh (the server keeps an identical box for 30 s so a repeat costs no credits). Read only.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Grid, type CellColor, type Column, type GridHandle } from "../components/Grid";
import { registerPanelKeys } from "../keys/panelKeys";
import { usePanelRefresh } from "./panelRefresh";
import type { FltRow } from "../net/types";
import { worldApi } from "../net/worldApi";
import { replaceView } from "../state/workspace";
import { useEnvelope } from "./useEnvelope";
import { creditsText, fltQuery, FLT_USAGE, fmtAge, fmtFeet, fmtHeading, fmtKt, fmtLatLon, fmtVrate, quietText, stepArea } from "./fltArgs";
import { EnvStatus, ErrorLine } from "./macroUi";
import { navKey } from "../keys/gridNav";
import { useLatest } from "../state/useLatest";
import type { FunctionProps } from "./registry";
import { gridCsv, useCsvExport } from "./tableExport";

// Colour carries meaning only: a climb is up, a descent is down, an aircraft on the ground is dim.
const vrateColor = (r: FltRow): CellColor => (r.vrate_fpm == null || r.vrate_fpm === 0 ? "fg" : r.vrate_fpm > 0 ? "up" : "down");

export default function FLT({ panelId, args }: FunctionProps) {
  const query = useMemo(() => fltQuery(args), [args]);
  const { env, error, loading, reload: load } = useEnvelope(query, (fresh) => worldApi.flt(query, fresh));
  const grid = useRef<GridHandle>(null);
  const [sel, setSel] = useState(0);
  const d = env?.data;
  const rows = useMemo(() => d?.rows ?? [], [d]);
  const latest = useLatest({ rows, query });

  const columns = useMemo<Column<FltRow>[]>(
    () => [
      { title: "CALLSIGN", width: 9, text: (r) => r.callsign || "(NONE)", color: (r) => (r.callsign ? "acc" : "dim") },
      { title: "COUNTRY", width: 20, text: (r) => r.country, color: () => "dim" },
      { title: "ALT FT", width: 7, align: "right", text: (r) => (r.on_ground ? "GND" : fmtFeet(r.alt_ft)), color: (r) => (r.on_ground ? "dim" : "fg") },
      { title: "KT", width: 4, align: "right", text: (r) => fmtKt(r.speed_kt), color: () => "fg" },
      { title: "HDG", width: 4, align: "right", text: (r) => fmtHeading(r.heading), color: () => "fg" },
      { title: "V/S FPM", width: 8, align: "right", text: (r) => fmtVrate(r.vrate_fpm), color: vrateColor },
      { title: "SQUAWK", width: 6, text: (r) => r.squawk, color: () => "dim" },
      { title: "POSITION", width: 17, text: (r) => fmtLatLon(r.lat, r.lon), color: () => "dim" },
      { title: "AGE", width: 5, align: "right", text: (r) => fmtAge(r.age_s), color: () => "dim" },
    ],
    [],
  );

  // The CSV keeps plain numbers in BOTH the source units (metres, m/s) and the display ones.
  useCsvExport(panelId, () =>
    d
      ? gridCsv(`FLT_${d.area}`.replace(/[^A-Z0-9_.-]/g, "_").slice(0, 60), [
          { title: "ICAO24", width: 7, text: (r: FltRow) => r.icao24 },
          { title: "CALLSIGN", width: 9, text: (r: FltRow) => r.callsign },
          { title: "COUNTRY", width: 20, text: (r: FltRow) => r.country },
          { title: "LAT", width: 10, text: (r: FltRow) => String(r.lat) },
          { title: "LON", width: 10, text: (r: FltRow) => String(r.lon) },
          { title: "BARO_ALT_M", width: 8, text: (r: FltRow) => (r.alt_m == null ? "" : String(r.alt_m)) },
          { title: "GEO_ALT_M", width: 8, text: (r: FltRow) => (r.geo_alt_m == null ? "" : String(r.geo_alt_m)) },
          { title: "ALT_FT", width: 7, text: (r: FltRow) => (r.alt_ft == null ? "" : String(r.alt_ft)) },
          { title: "SPEED_MS", width: 8, text: (r: FltRow) => (r.speed_ms == null ? "" : String(r.speed_ms)) },
          { title: "SPEED_KT", width: 8, text: (r: FltRow) => (r.speed_kt == null ? "" : String(r.speed_kt)) },
          { title: "HEADING", width: 7, text: (r: FltRow) => (r.heading == null ? "" : String(r.heading)) },
          { title: "VRATE_MS", width: 8, text: (r: FltRow) => (r.vrate_ms == null ? "" : String(r.vrate_ms)) },
          { title: "VRATE_FPM", width: 9, text: (r: FltRow) => (r.vrate_fpm == null ? "" : String(r.vrate_fpm)) },
          { title: "ON_GROUND", width: 9, text: (r: FltRow) => (r.on_ground ? "true" : "false") },
          { title: "SQUAWK", width: 6, text: (r: FltRow) => r.squawk },
          { title: "SOURCE", width: 7, text: (r: FltRow) => r.source },
          { title: "SEEN_UTC", width: 20, text: (r: FltRow) => (r.seen == null ? "" : new Date(r.seen * 1000).toISOString()) },
        ], rows)
      : null,
  );

  usePanelRefresh(panelId, () => { void load(true); });
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        if (e.ctrlKey || e.altKey || e.metaKey) return false;
        if (navKey(e, grid.current, latest.current.rows.length)) return true;
        const k = e.key.toLowerCase();
        if (k === "n" || k === "p") {
          // A new area is a new view argument, so the layout saves it and the load effect refetches.
          const next = stepArea(latest.current.query, k === "n" ? 1 : -1);
          replaceView(panelId, (v) => ({ ...v, args: [next] }));
          return true;
        }
        return false;
      }),
    [panelId, latest, load],
  );

  const cur = rows[sel];
  return (
    <div className="fn">
      <div className="line">
        <span className="acc">FLT</span> AIRCRAFT REPORTING POSITION · {d ? d.area : query}
        {d && <span className="dim"> · {rows.length} SHOWN OF {d.received} HEARD</span>}
        <EnvStatus env={env} loading={loading} />
        <span className="dim"> · N/P CITY · E CSV · F5 REFRESH</span>
      </div>
      {d?.fixture && <div className="warn">DOC-SHAPED TEST DATA, NOT A RECORDING AND NOT LIVE TRAFFIC (INVENTED AIRCRAFT IN OPENSKY'S DOCUMENTED LAYOUT)</div>}
      {d && <div className="dim">{d.note}</div>}
      {d && (
        <div className={d.authenticated ? "dim" : "warn"} data-testid="flt-access">
          {d.access} · {creditsText(d.credits_cost, d.credits_remaining)}
        </div>
      )}
      <ErrorLine error={error} hasData={!!d} usage={FLT_USAGE} />
      {loading && !d && !error && <div className="dim">ASKING OPENSKY…</div>}
      {d && d.rows.length === 0 && <div className="warn" data-testid="flt-quiet">{quietText(d.received)}</div>}
      {d && d.no_position > 0 && d.rows.length > 0 && <div className="dim">{d.no_position} MORE AIRCRAFT WERE HEARD WITHOUT A POSITION YET AND ARE LEFT OUT</div>}
      {d && d.truncated > 0 && <div className="warn">SHOWING {rows.length} AIRCRAFT; {d.truncated} MORE ARE LEFT OUT (E CSV HAS THE SAME {rows.length})</div>}
      {cur && (
        <div className="line" data-testid="flt-detail">
          <span className="acc">{cur.callsign || "(NO CALLSIGN)"}</span> · ICAO24 {cur.icao24} · REGISTERED IN {cur.country.toUpperCase()}
          {cur.alt_m != null && ` · BARO ALT ${fmtFeet(cur.alt_ft)} FT (${Math.round(cur.alt_m).toLocaleString("en-US")} M)`}
          {cur.geo_alt_m != null && ` · GPS ALT ${Math.round(cur.geo_alt_m).toLocaleString("en-US")} M`}
          {cur.on_ground && " · ON THE GROUND"}
          {cur.spi && <span className="warn"> · SPECIAL PURPOSE INDICATOR ON</span>}
          <span className="dim"> · POSITION FROM {cur.source}{cur.age_s != null && `, ${fmtAge(cur.age_s)} OLD`}</span>
        </div>
      )}
      {d && rows.length > 0 && <div className="dim">{d.country_note}</div>}
      <Grid ref={grid} columns={columns} rows={rows} onSelect={setSel} />
    </div>
  );
}
