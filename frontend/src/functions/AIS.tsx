/**
 * AIS: live ship positions inside a chokepoint box or your own box, from AISstream (free beta WebSocket, key AISSTREAM_API_KEY in APIKEYS).
 * `AIS SUEZ` / `AIS HORMUZ` ... or `AIS BOX <SOUTH> <WEST> <NORTH> <EAST>`. The server listens for about 15 seconds (the free feed is sparse: expect 0-5 ships per listen, and none at Suez or Hormuz) and keeps the newest
 * position per ship. It also REMEMBERS each ship's last position for 5 minutes, so a repeat listen adds ships heard earlier: those rows
 * are dimmed, say MEMORY in the FROM column and show their age, and nothing older than 5 minutes is ever shown. These are positions AS REPORTED BY SHIPS: late, switched off, spoofed or missing are all possible, and a short
 * listen is a sample, not a count. Destination and ETA are typed by the crew and arrive only every few minutes per ship.
 * Keys: arrows move, N / P next / previous chokepoint, E CSV, F5 listens again. Read only.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Grid, type CellColor, type Column, type GridHandle } from "../components/Grid";
import { registerPanelKeys } from "../keys/panelKeys";
import { usePanelRefresh } from "./panelRefresh";
import { mapArgsFor, openMap } from "../map/jump";
import type { AisRow } from "../net/types";
import { worldApi } from "../net/worldApi";
import { replaceView } from "../state/workspace";
import { fmtAge, fmtDegrees, fmtEta, fmtFrom, fmtKnots, fmtLatLon, aisQuery, listeningText, memoryNote, quietText, stepArea } from "./aisArgs";
import { useEnvelope } from "./useEnvelope";
import { EnvStatus, ErrorLine } from "./panelStatus";
import { navKey } from "../keys/gridNav";
import { useLatest } from "../state/useLatest";
import type { FunctionProps } from "./registry";
import { gridCsv, useCsvExport } from "./tableExport";

// A ship that reports it is not under control or aground is the one thing worth colouring; everything else stays neutral.
const TROUBLE = new Set(["NOT UNDER COMMAND", "AGROUND"]);

// A row remembered from an earlier listen is drawn dim in every column, so it cannot be mistaken for a ship heard just now.
// (The trouble colour is dropped too: a 4 minute old "aground" is not a live alarm.)
const aged = (r: AisRow, normal: CellColor): CellColor => (r.remembered ? "dim" : normal);

export default function AIS({ panelId, args }: FunctionProps) {
  const query = useMemo(() => aisQuery(args), [args]);
  const { env, error, loading, reload: load } = useEnvelope(query, (fresh) => worldApi.ais(query, fresh));
  const grid = useRef<GridHandle>(null);
  const [sel, setSel] = useState(0);
  const d = env?.data;
  const rows = useMemo(() => d?.rows ?? [], [d]);
  const latest = useLatest({ rows, query });
  // "Seen N ago" is measured against the clock when the panel last got data, so the column does not change by itself.
  // eslint-disable-next-line react-hooks/exhaustive-deps -- env is a deliberate re-run trigger (new data = new clock reading), not a value read
  const nowSec = useMemo(() => Date.now() / 1000, [env]);

  const columns = useMemo<Column<AisRow>[]>(
    () => [
      { title: "NAME", width: 22, text: (r) => r.name || "(NO NAME)", color: (r) => aged(r, r.name ? "acc" : "dim") },
      { title: "MMSI", width: 10, text: (r) => String(r.mmsi), color: () => "dim" },
      { title: "TYPE", width: 14, text: (r) => r.type, color: () => "dim" },
      { title: "KN", width: 5, align: "right", text: (r) => fmtKnots(r.sog), color: (r) => aged(r, "fg") },
      { title: "COG", width: 4, align: "right", text: (r) => fmtDegrees(r.cog), color: (r) => aged(r, "fg") },
      { title: "STATUS", width: 20, text: (r) => r.nav_name, color: (r) => aged(r, TROUBLE.has(r.nav_name) ? "warn" : "dim") },
      { title: "DESTINATION", width: 20, text: (r) => r.dest ?? "", color: (r) => aged(r, "fg") },
      { title: "ETA (UTC)", width: 11, text: (r) => fmtEta(r.eta), color: () => "dim" },
      { title: "POSITION", width: 17, text: (r) => fmtLatLon(r.lat, r.lon), color: () => "dim" },
      // AGE = how old the position report is (live rows are seconds old, remembered ones up to 5 minutes); FROM says which kind of row it is.
      { title: "AGE", width: 5, align: "right", text: (r) => fmtAge(nowSec - r.seen), color: () => "dim" },
      { title: "FROM", width: 6, text: (r) => fmtFrom(r.remembered), color: (r) => (r.remembered ? "warn" : "dim") },
    ],
    [nowSec],
  );

  // The CSV keeps plain numbers and the full values (the table shortens and rounds).
  useCsvExport(panelId, () =>
    d
      ? gridCsv(`AIS_${d.area}`.replace(/[^A-Z0-9_.-]/g, "_").slice(0, 60), [
          { title: "MMSI", width: 10, text: (r: AisRow) => String(r.mmsi) },
          { title: "NAME", width: 22, text: (r: AisRow) => r.name },
          { title: "IMO", width: 9, text: (r: AisRow) => (r.imo == null ? "" : String(r.imo)) },
          { title: "TYPE", width: 14, text: (r: AisRow) => r.type },
          { title: "SOG_KN", width: 6, text: (r: AisRow) => (r.sog == null ? "" : String(r.sog)) },
          { title: "COG", width: 5, text: (r: AisRow) => (r.cog == null ? "" : String(r.cog)) },
          { title: "HEADING", width: 7, text: (r: AisRow) => (r.heading == null ? "" : String(r.heading)) },
          { title: "STATUS", width: 20, text: (r: AisRow) => r.nav_name },
          { title: "DESTINATION", width: 20, text: (r: AisRow) => r.dest ?? "" },
          { title: "ETA_UTC", width: 11, text: (r: AisRow) => r.eta ?? "" },
          { title: "LAT", width: 10, text: (r: AisRow) => String(r.lat) },
          { title: "LON", width: 10, text: (r: AisRow) => String(r.lon) },
          { title: "SEEN_UTC", width: 20, text: (r: AisRow) => new Date(r.seen * 1000).toISOString() },
          { title: "FROM", width: 6, text: (r: AisRow) => fmtFrom(r.remembered) },
        ], rows)
      : null,
  );

  usePanelRefresh(panelId, () => { void load(true); });
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        if (navKey(e, grid.current, latest.current.rows.length)) return true;
        const k = e.key.toLowerCase();
        if (k === "m") {
          // M = show this area on the map (a custom BOX has no map area, so M does nothing there)
          const words = mapArgsFor("AIS", latest.current.query);
          if (!words) return false;
          openMap(panelId, words);
          return true;
        }
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
        <span className="acc">AIS</span> SHIPS REPORTING POSITION · {d ? d.area : query}
        {d && (
          <span className="dim">
            {" "}· {rows.length} SHIPS IN {d.listened_s.toFixed(0)} S{d.remembered > 0 && ` (${d.remembered} FROM MEMORY)`}
          </span>
        )}
        <EnvStatus env={env} loading={loading} />
        <span className="dim"> · N/P AREA · M MAP · E CSV · F5 LISTEN AGAIN</span>
      </div>
      {d?.fixture && <div className="warn">REPLAY OF A REAL AISSTREAM RECORDING FROM 2026-11-05 (OLD POSITIONS, ONLY SHIPS INSIDE THIS BOX): NOT LIVE TRAFFIC</div>}
      {d && <div className="dim">{d.note}</div>}
      {d && d.remembered > 0 && <div className="dim" data-testid="ais-memory">{memoryNote(d.memory_s)}</div>}
      <ErrorLine error={error} hasData={!!d} usage="AIS <SUEZ|PANAMA|HORMUZ|MALACCA|BABEL|BOSPHORUS|GIBRALTAR|DOVER> OR AIS BOX <S> <W> <N> <E>" />
      {loading && !d && !error && <div className="dim">{listeningText()}</div>}
      {d && d.rows.length === 0 && <div className="warn" data-testid="ais-quiet">{quietText(d.listened_s, d.received)}</div>}
      {d?.capped && <div className="warn">MESSAGE CAP REACHED BEFORE THE TIME WAS UP: THE LIST IS A SAMPLE OF A BUSY AREA</div>}
      {d && d.truncated > 0 && <div className="warn">SHOWING THE NEWEST {rows.length} SHIPS; {d.truncated} OLDER ONES ARE LEFT OUT (E CSV HAS THE SAME {rows.length})</div>}
      {cur && (
        <div className="line" data-testid="ais-detail">
          <span className="acc">{cur.name || "(NO NAME)"}</span> · MMSI {cur.mmsi}
          {cur.imo != null && ` · IMO ${cur.imo}`}
          {cur.length != null && ` · ${cur.length} M LONG`}
          {cur.draught != null && ` · DRAUGHT ${cur.draught} M`}
          {cur.heading != null && ` · HEADING ${cur.heading}`}
          {cur.remembered && <span className="warn"> · REMEMBERED FROM AN EARLIER LISTEN, REPORTED {fmtAge(cur.age_s)} AGO</span>}
          {cur.static_age_s != null && <span className="dim"> · DESTINATION AND ETA TYPED BY THE CREW, RECEIVED {fmtAge(cur.static_age_s)} AGO</span>}
          {cur.static_age_s == null && <span className="dim"> · NO VOYAGE DATA RECEIVED YET FOR THIS SHIP (IT SENDS EVERY FEW MINUTES)</span>}
        </div>
      )}
      <Grid ref={grid} columns={columns} rows={rows} onSelect={setSel} />
    </div>
  );
}
