/**
 * UKCO: UK Companies House register (free key COMPANIES_HOUSE_KEY, see APIKEYS).
 * `UKCO tesco` searches by name (Enter opens the highlighted company); `UKCO 00445790` shows one company: profile, officers and filing history.
 * Keys: arrows move, V switches OFFICERS / FILINGS, Enter opens a search result, E CSV, F5 refresh.
 * Register data as filed by each company; birth dates and home addresses of officers are never shown.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { registerPanelKeys } from "../keys/panelKeys";
import { usePanelRefresh } from "./panelRefresh";
import type { UkcoFiling, UkcoOfficer, UkcoPayload, UkcoSearchRow } from "../net/types";
import { worldApi } from "../net/worldApi";
import { navigate } from "../state/workspace";
import { useEnvelope } from "./useEnvelope";
import { EnvStatus, ErrorLine } from "./macroUi";
import { navKey } from "../keys/gridNav";
import { useLatest } from "../state/useLatest";
import type { FunctionProps } from "./registry";
import { gridCsv, useCsvExport } from "./tableExport";
import { dueText, readable, statusClass, ukcoQuery, yesNo } from "./ukcoArgs";

const SEARCH: Column<UkcoSearchRow>[] = [
  { title: "NUMBER", width: 10, text: (r) => r.number, color: () => "acc" },
  { title: "NAME", width: 38, text: (r) => r.name ?? "" },
  { title: "STATUS", width: 12, text: (r) => (r.status ?? "").toUpperCase(), color: (r) => statusClass(r.status) },
  { title: "TYPE", width: 14, text: (r) => readable(r.type), color: () => "dim" },
  { title: "CREATED", width: 11, text: (r) => r.created ?? "", color: () => "dim" },
  { title: "ADDRESS", width: 56, text: (r) => r.address, color: () => "dim" },
];
const OFFICERS: Column<UkcoOfficer>[] = [
  { title: "NAME", width: 34, text: (r) => r.name ?? "", color: (r) => (r.resigned ? "dim" : "fg") },
  { title: "ROLE", width: 18, text: (r) => r.role, color: () => "dim" },
  { title: "APPOINTED", width: 11, text: (r) => r.appointed ?? "" },
  { title: "RESIGNED", width: 11, text: (r) => r.resigned ?? "" },
  { title: "NATIONALITY", width: 16, text: (r) => r.nationality ?? "", color: () => "dim" },
  { title: "OCCUPATION", width: 26, text: (r) => r.occupation ?? "", color: () => "dim" },
  { title: "RESIDENCE", width: 16, text: (r) => r.country ?? "", color: () => "dim" },
];
const FILINGS: Column<UkcoFiling>[] = [
  { title: "DATE", width: 11, text: (r) => r.date ?? "" },
  { title: "CATEGORY", width: 24, text: (r) => r.category, color: () => "dim" },
  { title: "TYPE", width: 8, text: (r) => r.type ?? "", color: () => "acc" },
  { title: "DESCRIPTION", width: 70, text: (r) => r.description },
  { title: "PAGES", width: 6, align: "right", text: (r) => (r.pages == null ? "" : String(r.pages)), color: () => "dim" },
  { title: "PAPER", width: 6, text: (r) => (r.paper ? "PAPER" : ""), color: () => "dim" },
];

export default function UKCO({ panelId, args }: FunctionProps) {
  const query = useMemo(() => ukcoQuery(args), [args]);
  if (!query) {
    return (
      <div className="fn">
        <div className="line">
          <span className="acc">UKCO</span> UK COMPANIES HOUSE
        </div>
        <div className="dim">USAGE: UKCO &lt;COMPANY NAME&gt; to search, or UKCO &lt;COMPANY NUMBER&gt; (for example 00445790) for its profile, officers and filings.</div>
      </div>
    );
  }
  return <UkcoView panelId={panelId} query={query} />;
}

function UkcoView({ panelId, query }: { panelId: number; query: string }) {
  const { env, error, loading, reload: load } = useEnvelope(query.toLowerCase(), (fresh) => worldApi.ukco(query, fresh));
  const [view, setView] = useState<"OFFICERS" | "FILINGS">("OFFICERS");
  const grid = useRef<GridHandle>(null);
  const d: UkcoPayload | undefined = env?.data;
  const search = d?.mode === "SEARCH" ? d.items : null;
  const company = d?.mode === "COMPANY" ? d : null;
  const officers = useMemo(() => company?.officers?.items ?? [], [company]);
  const filings = useMemo(() => company?.filings?.items ?? [], [company]);
  const latest = useLatest({ search, view, officers, filings });
  useCsvExport(panelId, () => {
    if (search) return gridCsv("UKCO_SEARCH", SEARCH, search);
    if (!company) return null;
    return view === "OFFICERS" ? gridCsv(`UKCO_${company.number}_OFFICERS`, OFFICERS, officers) : gridCsv(`UKCO_${company.number}_FILINGS`, FILINGS, filings);
  });

  usePanelRefresh(panelId, () => { void load(true); });
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        if (e.ctrlKey || e.altKey || e.metaKey) return false;
        const cur = latest.current;
        const g = grid.current;
        const n = cur.search ? cur.search.length : cur.view === "OFFICERS" ? cur.officers.length : cur.filings.length;
        if (navKey(e, g, n)) return true;
        if ((e.key === "v" || e.key === "V") && !cur.search) {
          setView((v) => (v === "OFFICERS" ? "FILINGS" : "OFFICERS"));
          return true;
        }
        if (e.key === "Enter" && cur.search) {
          const r = cur.search[g?.selected() ?? -1];
          if (r) navigate(panelId, { fn: "UKCO", args: [r.number], security: undefined });
          return true;
        }
        return false;
      }),
    [panelId, latest],
  );

  const p = company?.profile;
  return (
    <div className="fn">
      <div className="line">
        <span className="acc">UKCO</span> UK COMPANIES HOUSE · {d ? d.mode : "…"}
        {company && ` · ${view}`}
        <EnvStatus env={env} loading={loading} />
        <span className="dim"> · {search ? "ENTER OPEN · " : "V OFFICERS/FILINGS · "}E CSV · F5</span>
      </div>
      <ErrorLine error={error} hasData={!!d} usage="UKCO <NAME|NUMBER>" />
      {p && (
        <div data-testid="ukco-profile">
          <div className="line">
            <span className="acc">{p.name}</span> ({p.number}) · <span className={statusClass(p.status)}>{(p.status ?? "STATUS NOT GIVEN").toUpperCase()}</span>
            {p.status_detail && <span className="warn"> · {readable(p.status_detail)}</span>}
            <span className="dim"> · {readable(p.type)}{p.subtype ? ` ${readable(p.subtype)}` : ""} · {readable(p.jurisdiction)} · INCORPORATED {p.created ?? "DATE NOT GIVEN"}{p.ceased ? ` · CEASED ${p.ceased}` : ""}</span>
          </div>
          <div className="line dim">REGISTERED OFFICE: {p.address || "NOT GIVEN"}{p.sic.length > 0 && ` · SIC ${p.sic.join(", ")}`}</div>
          <div className="line">
            ACCOUNTS: LAST TO {p.accounts.last_made_up_to ?? "NONE FILED"} · NEXT DUE{" "}
            <span className={p.accounts.overdue ? "warn" : "fg"}>{dueText(p.accounts.next_due, p.accounts.overdue) || "NOT GIVEN"}</span>
            <span className="dim"> · CONFIRMATION STATEMENT DUE </span>
            <span className={p.confirmation.overdue ? "warn" : "fg"}>{dueText(p.confirmation.next_due, p.confirmation.overdue) || "NOT GIVEN"}</span>
            <span className="dim"> · CHARGES {yesNo(p.has_charges)} · INSOLVENCY HISTORY {yesNo(p.has_insolvency_history)}</span>
          </div>
          {company && company.notes.map((n) => (
            <div key={n} className="warn">{n}</div>
          ))}
          {company && (
            <div className="dim">
              OFFICERS {company.officers ? `${company.officers.active ?? "?"} ACTIVE, ${company.officers.resigned ?? "?"} RESIGNED${(company.officers.total ?? 0) > company.officers.items.length ? ` (FIRST ${company.officers.items.length} SHOWN)` : ""}` : "NOT LOADED"}
              {" · "}FILINGS {company.filings ? `${company.filings.total ?? "?"} IN ALL, LATEST ${company.filings.items.length} SHOWN` : "NOT LOADED"}
            </div>
          )}
        </div>
      )}
      {d && <div className="dim">{d.note}</div>}
      {search ? (
        <Grid key="search" ref={grid} columns={SEARCH} rows={search} />
      ) : company ? (
        view === "OFFICERS" ? (
          <Grid key="officers" ref={grid} columns={OFFICERS} rows={officers} />
        ) : (
          <Grid key="filings" ref={grid} columns={FILINGS} rows={filings} />
        )
      ) : null}
    </div>
  );
}
