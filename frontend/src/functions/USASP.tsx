/**
 * USASP: US federal spending from USASpending.gov (keyless).
 * `USASP lockheed martin` = top contract recipients and the largest awards over the last three fiscal years; `USASP` or `USASP AGENCY` = top awarding agencies
 * (Enter opens an agency's top contract recipients). Keys: arrows move, V switches RECIPIENTS / AWARDS, Enter opens an agency, B back to agencies, E CSV, F5 refresh.
 * Every amount is US dollars OBLIGATED (committed), not paid and not the recipient's revenue; the panel says so under the title.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { registerPanelKeys } from "../keys/panelKeys";
import { worldApi, type UsaspAgency, type UsaspAward, type UsaspPayload, type UsaspRecipient } from "../net/api";
import { navigate } from "../state/workspace";
import { useEnvLoad } from "./cryptoLoad";
import { EnvStatus, ErrorLine } from "./macroUi";
import { navKey, useLatest } from "./quoteRows";
import type { FunctionProps } from "./registry";
import { gridCsv, useCsvExport } from "./tableExport";
import { fmtUsd, joinQuery } from "./usgovArgs";

const RECIPIENTS: Column<UsaspRecipient>[] = [
  { title: "RECIPIENT", width: 44, text: (r) => r.name, color: () => "acc" },
  { title: "OBLIGATED USD", width: 16, align: "right", text: (r) => fmtUsd(r.amount) },
  { title: "UEI", width: 14, text: (r) => r.uei ?? "", color: () => "dim" },
];
const AWARDS: Column<UsaspAward>[] = [
  { title: "AWARD ID", width: 18, text: (r) => r.award_id, color: () => "acc" },
  { title: "RECIPIENT", width: 30, text: (r) => r.recipient },
  { title: "AWARD TOTAL USD", width: 16, align: "right", text: (r) => fmtUsd(r.amount) },
  { title: "AGENCY", width: 30, text: (r) => r.agency, color: () => "dim" },
  { title: "START", width: 11, text: (r) => r.start ?? "", color: () => "dim" },
  { title: "END", width: 11, text: (r) => r.end ?? "", color: () => "dim" },
  { title: "DESCRIPTION", width: 60, text: (r) => r.description, color: () => "dim" },
];
const AGENCIES: Column<UsaspAgency>[] = [
  { title: "CODE", width: 8, text: (r) => r.code ?? "", color: () => "acc" },
  { title: "AGENCY", width: 56, text: (r) => r.name },
  { title: "OBLIGATED USD", width: 16, align: "right", text: (r) => fmtUsd(r.amount) },
];

export default function USASP({ panelId, args }: FunctionProps) {
  const query = useMemo(() => joinQuery(args), [args]);
  return <UsaspView panelId={panelId} query={query} />;
}

function UsaspView({ panelId, query }: { panelId: number; query: string }) {
  const { env, error, loading, load } = useEnvLoad((fresh) => worldApi.usasp(query, fresh), query.toLowerCase());
  const [view, setView] = useState<"RECIPIENTS" | "AWARDS">("RECIPIENTS");
  const grid = useRef<GridHandle>(null);
  const d: UsaspPayload | undefined = env?.data;
  const agencies = d?.mode === "AGENCY" ? d.agencies : null;
  const recipients = d?.mode === "KEYWORD" || d?.mode === "AGENCY_RECIPIENTS" ? d.recipients : null;
  const awards = d?.mode === "KEYWORD" ? d.awards : null;
  const showAwards = view === "AWARDS" && awards != null;
  const latest = useLatest({ agencies, recipients, awards, showAwards, mode: d?.mode });
  useCsvExport(panelId, () => {
    if (agencies) return gridCsv("USASP_AGENCIES", AGENCIES, agencies);
    if (showAwards && awards) return gridCsv("USASP_AWARDS", AWARDS, awards);
    return recipients ? gridCsv("USASP_RECIPIENTS", RECIPIENTS, recipients) : null;
  });

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        if (e.ctrlKey || e.altKey || e.metaKey) return false;
        const cur = latest.current;
        const g = grid.current;
        const n = cur.agencies ? cur.agencies.length : cur.showAwards ? (cur.awards?.length ?? 0) : (cur.recipients?.length ?? 0);
        if (navKey(e, g, n)) return true;
        if (e.key === "F5") {
          void load(true);
          return true;
        }
        if ((e.key === "v" || e.key === "V") && cur.mode === "KEYWORD") {
          setView((v) => (v === "RECIPIENTS" ? "AWARDS" : "RECIPIENTS"));
          return true;
        }
        if (e.key === "Enter" && cur.agencies) {
          const r = cur.agencies[g?.selected() ?? -1];
          // the agency's exact name travels in one argument after "AGENCY:"; the backend splits on the first colon only
          if (r) navigate(panelId, { fn: "USASP", args: [`AGENCY:${r.name}`], security: undefined });
          return true;
        }
        if ((e.key === "b" || e.key === "B") && cur.mode === "AGENCY_RECIPIENTS") {
          navigate(panelId, { fn: "USASP", args: ["AGENCY"], security: undefined });
          return true;
        }
        return false;
      }),
    [panelId, latest, load],
  );

  const title = d?.mode === "AGENCY" ? "TOP AGENCIES" : d?.mode === "AGENCY_RECIPIENTS" ? d.agency.toUpperCase() : d?.mode === "KEYWORD" ? d.query.toUpperCase() : "…";
  const empty = (d?.mode === "KEYWORD" && d.recipients.length === 0) || (d?.mode === "AGENCY_RECIPIENTS" && d.recipients.length === 0) || (d?.mode === "AGENCY" && d.agencies.length === 0);
  return (
    <div className="fn">
      <div className="line">
        <span className="acc">USASP</span> US FEDERAL SPENDING · {title}
        {d?.mode === "KEYWORD" && ` · ${view}`}
        <EnvStatus env={env} loading={loading} />
        <span className="dim"> · {d?.mode === "AGENCY" ? "ENTER OPEN · " : d?.mode === "KEYWORD" ? "V RECIPIENTS/AWARDS · " : d?.mode === "AGENCY_RECIPIENTS" ? "B BACK · " : ""}E CSV · F5</span>
      </div>
      <ErrorLine error={error} hasData={!!d} usage="USASP <COMPANY OR KEYWORD> | USASP AGENCY" />
      {d && (
        <div className="line dim" data-testid="usasp-window">
          {d.window} · {d.award_kind} · USD OBLIGATED
          {d.mode !== "AGENCY" && d.recipients_total != null && ` · TOP ${d.recipients.length} RECIPIENTS TOTAL ${fmtUsd(d.recipients_total)}`}
        </div>
      )}
      {d?.mode === "KEYWORD" && d.notes.map((n) => (
        <div key={n} className="warn">{n}</div>
      ))}
      {d && <div className="dim">{d.note}</div>}
      {empty && <div className="warn">NO AWARDS MATCH IN THIS WINDOW. TRY A SHORTER NAME (FOR EXAMPLE LOCKHEED) OR A DIFFERENT KEYWORD.</div>}
      {agencies ? (
        <Grid key="agencies" ref={grid} columns={AGENCIES} rows={agencies} />
      ) : showAwards && awards ? (
        <Grid key="awards" ref={grid} columns={AWARDS} rows={awards} />
      ) : recipients ? (
        <Grid key="recipients" ref={grid} columns={RECIPIENTS} rows={recipients} />
      ) : null}
    </div>
  );
}
