/**
 * FEC: US campaign finance from OpenFEC (free key FEC_API_KEY from api.data.gov, see APIKEYS; without it the panel says KEY REQUIRED).
 * `FEC smith` searches candidates and committees by name (Enter opens the highlighted one); `FEC H8CA12345` / `FEC C00123456` shows that candidate's or
 * committee's receipts, disbursements, cash and debts for the latest election cycle and the cycles before it. Keys: arrows move, Enter opens, E CSV, F5 refresh.
 * Figures are US dollars as reported to the FEC on filings (self-reported). DOC-SHAPED: built from the OpenFEC docs, never run against a live key.
 */
import { useEffect, useMemo, useRef } from "react";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { registerPanelKeys } from "../keys/panelKeys";
import { worldApi, type FecCycle, type FecItem, type FecPayload } from "../net/api";
import { navigate } from "../state/workspace";
import { useEnvLoad } from "./cryptoLoad";
import { EnvStatus, ErrorLine } from "./macroUi";
import { navKey, useLatest } from "./quoteRows";
import type { FunctionProps } from "./registry";
import { gridCsv, useCsvExport } from "./tableExport";
import { coverage, fecWhere, fmtUsd, joinQuery } from "./usgovArgs";

const SEARCH: Column<FecItem>[] = [
  { title: "KIND", width: 10, text: (r) => r.kind, color: (r) => (r.kind === "CANDIDATE" ? "acc" : "dim") },
  { title: "ID", width: 11, text: (r) => r.id },
  { title: "NAME", width: 50, text: (r) => r.name },
  { title: "PARTY", width: 26, text: (r) => r.party ?? "", color: () => "dim" },
  { title: "OFFICE / TYPE", width: 30, text: (r) => fecWhere(r), color: () => "dim" },
  { title: "LAST CYCLE", width: 10, align: "right", text: (r) => (r.last_year == null ? "" : String(r.last_year)), color: () => "dim" },
];
const CYCLES: Column<FecCycle>[] = [
  { title: "CYCLE", width: 7, text: (r) => String(r.cycle), color: () => "acc" },
  { title: "RECEIPTS", width: 13, align: "right", text: (r) => fmtUsd(r.receipts) },
  { title: "DISBURSEMENTS", width: 14, align: "right", text: (r) => fmtUsd(r.disbursements) },
  { title: "CASH ON HAND", width: 13, align: "right", text: (r) => fmtUsd(r.cash) },
  { title: "DEBTS", width: 11, align: "right", text: (r) => fmtUsd(r.debts) },
  { title: "FROM INDIVIDUALS", width: 16, align: "right", text: (r) => fmtUsd(r.individual) },
  { title: "COVERED TO", width: 11, text: (r) => coverage(r.covered_to), color: () => "dim" },
];

export default function FEC({ panelId, args }: FunctionProps) {
  const query = useMemo(() => joinQuery(args), [args]);
  if (!query) {
    return (
      <div className="fn">
        <div className="line"><span className="acc">FEC</span> US CAMPAIGN FINANCE (OPENFEC)</div>
        <div className="dim">USAGE: FEC &lt;CANDIDATE OR COMMITTEE NAME&gt; to search, or FEC &lt;FEC ID&gt; (H8CA12345 for a candidate, C00123456 for a committee) for its totals.</div>
        <div className="dim">NEEDS A FREE KEY: FEC_API_KEY from api.data.gov (APIKEYS).</div>
      </div>
    );
  }
  return <FecView panelId={panelId} query={query} />;
}

function FecView({ panelId, query }: { panelId: number; query: string }) {
  const { env, error, loading, load } = useEnvLoad((fresh) => worldApi.fec(query, fresh), query.toLowerCase());
  const grid = useRef<GridHandle>(null);
  const d: FecPayload | undefined = env?.data;
  const search = d?.mode === "SEARCH" ? d.items : null;
  const entity = d && d.mode !== "SEARCH" ? d : null;
  const cycles = useMemo(() => entity?.cycles ?? [], [entity]);
  const latest = useLatest({ search, cycles });
  useCsvExport(panelId, () => {
    if (search) return gridCsv("FEC_SEARCH", SEARCH, search);
    return entity ? gridCsv(`FEC_${entity.id}`, CYCLES, cycles) : null;
  });

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        if (e.ctrlKey || e.altKey || e.metaKey) return false;
        const cur = latest.current;
        const g = grid.current;
        if (navKey(e, g, cur.search ? cur.search.length : cur.cycles.length)) return true;
        if (e.key === "F5") {
          void load(true);
          return true;
        }
        if (e.key === "Enter" && cur.search) {
          const r = cur.search[g?.selected() ?? -1];
          if (r) navigate(panelId, { fn: "FEC", args: [r.id], security: undefined });
          return true;
        }
        return false;
      }),
    [panelId, latest, load],
  );

  const l = entity?.latest;
  return (
    <div className="fn">
      <div className="line">
        <span className="acc">FEC</span> US CAMPAIGN FINANCE · {entity ? `${entity.mode} ${entity.id}` : d ? "SEARCH" : "…"}
        <EnvStatus env={env} loading={loading} />
        <span className="dim"> · {search ? "ENTER OPEN · " : ""}E CSV · F5</span>
      </div>
      <ErrorLine error={error} hasData={!!d} usage="FEC <NAME|FEC ID>" />
      {d?.mode === "SEARCH" && d.notes.map((n) => (
        <div key={n} className="warn">{n}</div>
      ))}
      {entity && (
        <div data-testid="fec-summary">
          <div className="line"><span className="acc">{entity.name}</span> ({entity.id})</div>
          {l ? (
            <div className="line">
              LATEST CYCLE {l.cycle} · RECEIPTS {fmtUsd(l.receipts) || "NOT GIVEN"} · DISBURSEMENTS {fmtUsd(l.disbursements) || "NOT GIVEN"} · CASH ON HAND {fmtUsd(l.cash) || "NOT GIVEN"}
              <span className="dim"> · DEBTS {fmtUsd(l.debts) || "NOT GIVEN"} · COVERED TO {coverage(l.covered_to)}</span>
            </div>
          ) : (
            <div className="warn">NO TOTALS FILED FOR THIS ID YET.</div>
          )}
        </div>
      )}
      {d && <div className="dim">{d.note}</div>}
      {d?.mode === "SEARCH" && d.items.length === 0 && <div className="warn">NO CANDIDATE OR COMMITTEE NAME MATCHES.</div>}
      {search ? <Grid key="search" ref={grid} columns={SEARCH} rows={search} /> : entity ? <Grid key="cycles" ref={grid} columns={CYCLES} rows={cycles} /> : null}
    </div>
  );
}
