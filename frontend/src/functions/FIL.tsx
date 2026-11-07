/** SEC filings index (SEC is an alias): newest first, form filter, Enter opens the document on sec.gov. */
import { useEffect, useMemo, useRef, useState } from "react";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { registerPanelKeys } from "../keys/panelKeys";
import { usePanelRefresh } from "./panelRefresh";
import { secApi } from "../net/secApi";
import { navKey } from "../keys/gridNav";
import { useLatest } from "../state/useLatest";
import type { FunctionProps } from "./registry";
import { ErrorLine, Header, openUrl, useEnvelope } from "./secPanel";
import { filingForm, type Filing, type FilingsPayload } from "./secTables";
import { gridCsv, useCsvExport } from "./tableExport";

const QUICK = ["", "10-K", "10-Q", "8-K", "4", "DEF 14A"];
const label = (f: string) => f || "ALL";

const COLUMNS: Column<Filing>[] = [
  { title: "FILED", width: 10, text: (r) => r.filed, color: () => "dim" },
  { title: "FORM", width: 8, text: (r) => r.form, color: () => "acc" },
  { title: "PERIOD", width: 10, text: (r) => r.report_date ?? "", color: () => "dim" },
  { title: "DESCRIPTION", width: 44, text: (r) => r.description },
  { title: "ITEMS", width: 22, text: (r) => r.items ?? "", color: () => "dim" },
  { title: "ACCESSION", width: 20, text: (r) => r.accession, color: () => "dim" },
];

export default function FIL({ panelId, security, args }: FunctionProps) {
  const symbol = security!.symbol;
  const [form, setForm] = useState(() => filingForm(args));
  const grid = useRef<GridHandle>(null);
  const { env, error, loading, reload } = useEnvelope<FilingsPayload>(`${symbol}|${form}`, (fresh) => secApi.filings(symbol, form, fresh));
  const rows = useMemo(() => env?.data.filings ?? [], [env]);
  const latest = useLatest({ rows, form });
  useCsvExport(panelId, () => gridCsv(`FIL_${symbol}_${label(form)}`, COLUMNS, rows));

  usePanelRefresh(panelId, () => { void reload(true); });
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const g = grid.current;
        const { rows: cur, form: f } = latest.current;
        if (navKey(e, g, cur.length)) return true;
        const n = Number(e.key);
        if (e.key.length === 1 && n >= 1 && n <= QUICK.length) {
          setForm(QUICK[n - 1]);
          g?.moveTo(0);
          return true;
        }
        switch (e.key) {
          case "Tab": {
            const i = QUICK.indexOf(f);
            setForm(QUICK[(i + (e.shiftKey ? QUICK.length - 1 : 1) + (i < 0 ? 1 : 0)) % QUICK.length]);
            g?.moveTo(0);
            return true;
          }
          case "Enter":
          case "o": {
            const r = cur[g?.selected() ?? -1];
            if (r) openUrl(r.doc_url ?? r.url);
            return true;
          }
          case "i": {
            const r = cur[g?.selected() ?? -1];
            if (r) openUrl(r.url);
            return true;
          }
        }
        return false;
      }),
    [panelId, latest, symbol],
  );

  const d = env?.data;
  return (
    <div className="fn">
      <Header
        title={`FIL ${symbol}${d?.name ? ` · ${d.name.toUpperCase()}` : ""}`}
        env={env}
        loading={loading}
        extra={d && ` · ${rows.length} OF ${d.total} FILINGS${d.fiscal_year_end ? ` · FYE ${d.fiscal_year_end}` : ""}`}
        keys="1-6/TAB FORM · J/K MOVE · ENTER OPEN · I INDEX · E CSV · F5 REFRESH"
      />
      <div className="tabs">
        {QUICK.map((f, i) => (
          <span key={f} className={f === form ? "on" : "dim"}>
            {i + 1} {label(f)}
          </span>
        ))}
        {form && !QUICK.includes(form) && <span className="on">FORM {form}</span>}
      </div>
      <ErrorLine error={error} hasData={!!env} />
      {d && rows.length === 0 && !error && <div className="warn">NO {label(form)} FILINGS FOR {symbol}</div>}
      <Grid ref={grid} columns={COLUMNS} rows={rows} />
      <div className="summary dim">opens on sec.gov in a new tab · filing text is not scraped here</div>
    </div>
  );
}
