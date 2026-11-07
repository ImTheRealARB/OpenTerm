/**
 * FEDREG: the US Federal Register (keyless), newest documents first.
 * `FEDREG semiconductor` searches; a first word RULE / PROPOSED / NOTICE / PRESDOC limits the type (`FEDREG RULE chips`); `FEDREG` alone = the newest documents.
 * Keys: arrows move, Enter shows the agency's own abstract and the link id of the highlighted document, E CSV, F5 refresh.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { registerPanelKeys } from "../keys/panelKeys";
import { usePanelRefresh } from "./panelRefresh";
import type { FedregItem } from "../net/types";
import { worldApi } from "../net/worldApi";
import { useEnvelope } from "./useEnvelope";
import { EnvStatus, ErrorLine } from "./panelStatus";
import { navKey } from "../keys/gridNav";
import { useLatest } from "../state/useLatest";
import type { FunctionProps } from "./registry";
import { gridCsv, useCsvExport } from "./tableExport";
import { agencyShort, joinQuery } from "./usgovArgs";

const COLUMNS: Column<FedregItem>[] = [
  { title: "DATE", width: 11, text: (r) => r.date ?? "", color: () => "dim" },
  { title: "TYPE", width: 20, text: (r) => r.type.toUpperCase(), color: () => "acc" },
  { title: "AGENCY", width: 38, text: (r) => agencyShort(r.agencies), color: () => "dim" },
  { title: "TITLE", width: 110, text: (r) => r.title },
  { title: "DOC NO", width: 12, text: (r) => r.number, color: () => "dim" },
];

export default function FEDREG({ panelId, args }: FunctionProps) {
  const query = useMemo(() => joinQuery(args), [args]);
  const { env, error, loading, reload: load } = useEnvelope(query.toLowerCase(), (fresh) => worldApi.fedreg(query, fresh));
  const [open, setOpen] = useState<string | null>(null); // document number whose abstract is shown
  const grid = useRef<GridHandle>(null);
  const d = env?.data;
  const items = useMemo(() => d?.items ?? [], [d]);
  const latest = useLatest({ items });
  useCsvExport(panelId, () => (d ? gridCsv("FEDREG", COLUMNS, items, [{ title: "ABSTRACT", text: (r) => r.abstract ?? "" }, { title: "URL", text: (r) => r.url ?? "" }]) : null));

  usePanelRefresh(panelId, () => { void load(true); });
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const g = grid.current;
        const rows = latest.current.items;
        if (navKey(e, g, rows.length)) return true;
        if (e.key === "Enter") {
          const r = rows[g?.selected() ?? -1];
          if (r) setOpen((cur) => (cur === r.number ? null : r.number)); // Enter again hides it
          return true;
        }
        return false;
      }),
    [panelId, latest],
  );

  const shown = open ? items.find((i) => i.number === open) : undefined;
  return (
    <div className="fn">
      <div className="line">
        <span className="acc">FEDREG</span> FEDERAL REGISTER · {d ? (d.query ? d.query.toUpperCase() : "NEWEST") : "…"}
        {d?.type && ` · ${d.type}`}
        <EnvStatus env={env} loading={loading} />
        <span className="dim"> · ENTER ABSTRACT · E CSV · F5</span>
      </div>
      <ErrorLine error={error} hasData={!!d} usage="FEDREG [RULE|PROPOSED|NOTICE|PRESDOC] <WORDS>" />
      {d && (
        <div className="line dim" data-testid="fedreg-count">
          {d.total === 0 ? "NO DOCUMENTS MATCH" : `${d.total.toLocaleString("en-US")} DOCUMENTS MATCH${d.total > d.shown ? ` · NEWEST ${d.shown} SHOWN` : ""}`}
        </div>
      )}
      {d && <div className="dim">{d.note}</div>}
      {shown && (
        <div data-testid="fedreg-detail">
          <div className="line"><span className="acc">{shown.number}</span> · {shown.agencies.join(", ") || "AGENCY NOT GIVEN"} · {shown.date ?? "DATE NOT GIVEN"}</div>
          <div>{shown.abstract ?? "THE AGENCY GAVE NO ABSTRACT FOR THIS DOCUMENT."}</div>
          <div className="dim">{shown.url ?? "NO LINK GIVEN"}</div>
        </div>
      )}
      {d && <Grid ref={grid} columns={COLUMNS} rows={items} />}
    </div>
  );
}
