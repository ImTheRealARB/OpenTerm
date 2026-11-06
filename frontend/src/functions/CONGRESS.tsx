/**
 * CONGRESS: US bills from the Congress.gov API v3 (free key CONGRESS_API_KEY from api.data.gov, see APIKEYS; without it the panel says KEY REQUIRED).
 * `CONGRESS` = the latest updated bills; `CONGRESS chips` = a title filter over the 250 most recently updated bills (the API has no text search, the panel says so);
 * `CONGRESS HR 1234` (or Enter on a row) opens one bill with its sponsor. Keys: arrows move, Enter opens, E CSV, F5 refresh.
 * DOC-SHAPED: built from the Congress.gov docs, never run against a live key.
 */
import { useEffect, useMemo, useRef } from "react";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { registerPanelKeys } from "../keys/panelKeys";
import { usePanelRefresh } from "./panelRefresh";
import type { CongressPayload, CongressRow } from "../net/types";
import { worldApi } from "../net/worldApi";
import { navigate } from "../state/workspace";
import { useEnvelope } from "./useEnvelope";
import { EnvStatus, ErrorLine } from "./macroUi";
import { navKey } from "../keys/gridNav";
import { useLatest } from "../state/useLatest";
import type { FunctionProps } from "./registry";
import { gridCsv, useCsvExport } from "./tableExport";
import { billCommandArgs, billLabel, joinQuery } from "./usgovArgs";

const BILLS: Column<CongressRow>[] = [
  { title: "BILL", width: 10, text: (r) => billLabel(r), color: () => "acc" },
  { title: "CONG", width: 5, align: "right", text: (r) => String(r.congress), color: () => "dim" },
  { title: "TITLE", width: 80, text: (r) => r.title },
  { title: "LAST ACTION", width: 11, text: (r) => r.action_date ?? "", color: () => "dim" },
  { title: "ACTION", width: 70, text: (r) => r.action, color: () => "dim" },
  { title: "UPDATED", width: 11, text: (r) => r.updated ?? "", color: () => "dim" },
];
interface Field { field: string; value: string }
const FIELDS: Column<Field>[] = [
  { title: "FIELD", width: 16, text: (r) => r.field, color: () => "acc" },
  { title: "VALUE", width: 140, text: (r) => r.value },
];

/** The rows of one bill's detail table. A missing value says NOT GIVEN instead of vanishing. */
function billFields(b: Extract<CongressPayload, { mode: "BILL" }>): Field[] {
  const ng = (v: string | number | null | undefined) => (v == null || v === "" ? "NOT GIVEN" : String(v));
  return [
    { field: "BILL", value: `${b.type} ${b.number} (${b.congress}TH CONGRESS)` },
    { field: "TITLE", value: ng(b.title) },
    { field: "ORIGIN", value: ng(b.chamber) },
    { field: "INTRODUCED", value: ng(b.introduced) },
    { field: "SPONSOR", value: b.sponsors.length ? b.sponsors.join("; ") : "NOT GIVEN" },
    { field: "COSPONSORS", value: ng(b.cosponsors) },
    { field: "POLICY AREA", value: ng(b.policy_area) },
    { field: "LAST ACTION", value: `${ng(b.action_date)} ${b.action}`.trim() },
    { field: "UPDATED", value: ng(b.updated) },
  ];
}

export default function CONGRESS({ panelId, args }: FunctionProps) {
  const query = useMemo(() => joinQuery(args), [args]);
  const { env, error, loading, reload: load } = useEnvelope(query.toLowerCase(), (fresh) => worldApi.congress(query, fresh));
  const grid = useRef<GridHandle>(null);
  const d: CongressPayload | undefined = env?.data;
  const list = d && d.mode !== "BILL" ? d.items : null;
  const bill = d?.mode === "BILL" ? d : null;
  const fields = useMemo(() => (bill ? billFields(bill) : []), [bill]);
  const latest = useLatest({ list, fields });
  useCsvExport(panelId, () => (list ? gridCsv("CONGRESS_BILLS", BILLS, list) : bill ? gridCsv(`CONGRESS_${bill.type}${bill.number}`, FIELDS, fields) : null));

  usePanelRefresh(panelId, () => { void load(true); });
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        if (e.ctrlKey || e.altKey || e.metaKey) return false;
        const cur = latest.current;
        const g = grid.current;
        if (navKey(e, g, cur.list ? cur.list.length : cur.fields.length)) return true;
        if (e.key === "Enter" && cur.list) {
          const r = cur.list[g?.selected() ?? -1];
          if (r) navigate(panelId, { fn: "CONGRESS", args: billCommandArgs(r), security: undefined });
          return true;
        }
        return false;
      }),
    [panelId, latest],
  );

  return (
    <div className="fn">
      <div className="line">
        <span className="acc">CONGRESS</span> US BILLS · {bill ? `${bill.type} ${bill.number}` : d?.mode === "LATEST" ? "LATEST UPDATED" : d?.mode === "TITLE FILTER" ? `TITLE FILTER "${d.query.toUpperCase()}"` : "…"}
        <EnvStatus env={env} loading={loading} />
        <span className="dim"> · {list ? "ENTER OPEN BILL · " : ""}E CSV · F5</span>
      </div>
      <ErrorLine error={error} hasData={!!d} usage="CONGRESS [<WORDS> | HR 1234]" />
      {d && d.mode === "TITLE FILTER" && (
        <div className="line dim" data-testid="congress-count">
          {d.matched} OF THE {d.fetched} MOST RECENTLY UPDATED BILLS MATCH{d.matched > d.items.length ? ` · FIRST ${d.items.length} SHOWN` : ""}
        </div>
      )}
      {d && <div className="dim">{d.note}</div>}
      {d && d.mode === "TITLE FILTER" && d.items.length === 0 && <div className="warn">NO BILL TITLE AMONG THE LATEST UPDATED MATCHES. TO OPEN A KNOWN BILL TYPE ITS NUMBER, FOR EXAMPLE CONGRESS HR 1234.</div>}
      {list ? <Grid key="list" ref={grid} columns={BILLS} rows={list} /> : bill ? <Grid key="bill" ref={grid} columns={FIELDS} rows={fields} /> : null}
    </div>
  );
}
