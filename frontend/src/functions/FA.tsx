/** Financial analysis: income statement, balance sheet and cash flow from SEC XBRL company facts (annual or quarterly). */
import { useEffect, useMemo, useRef, useState } from "react";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { PanelNote } from "../components/PanelNote";
import { registerPanelKeys } from "../keys/panelKeys";
import { usePanelRefresh } from "./panelRefresh";
import { secApi } from "../net/secApi";
import { settingsStore } from "../settings/runtime";
import { useStore } from "../state/store";
import { navKey } from "../keys/gridNav";
import { useLatest } from "../state/useLatest";
import type { FunctionProps } from "./registry";
import { isKeyRequired } from "./KeyRequiredLine";
import { ErrorLine, Header, SEC_UA_HINT, SEC_UA_RE, US_ONLY, useEnvelope } from "./secPanel";
import { STATEMENT_TABS, faArgs, faRows, unitNote, type FaGridRow, type FaPayload, type FaPeriod, type StatementTab } from "./secTables";
import { useCsvExport } from "./tableExport";

const MAX_COLS = 12;

/** Statement lines that are totals or subtotals. In GUI mode they are drawn brighter ("val") so they stand out from the lines under them. */
const SUBTOTALS = new Set(["revenue", "gross_profit", "operating_income", "pretax_income", "net_income", "current_assets", "total_assets", "current_liabilities", "total_liabilities", "equity", "operating_cf", "investing_cf", "financing_cf"]);

export default function FA({ panelId, security, args }: FunctionProps) {
  const symbol = security!.symbol;
  const init = useMemo(() => faArgs(args), [args]);
  const [period, setPeriod] = useState<FaPeriod>(init.period);
  const [tab, setTab] = useState<StatementTab>(init.tab);
  const [offset, setOffset] = useState(0);
  const [sel, setSel] = useState(0);
  const grid = useRef<GridHandle>(null);
  const gui = useStore(settingsStore, (st) => st.mode === "gui");

  const { env, error, loading, reload } = useEnvelope<FaPayload>(`${symbol}|${period}`, (fresh) => secApi.fa(symbol, period, fresh));
  const shaped = useMemo(() => (env ? faRows(env.data, tab, offset, MAX_COLS) : null), [env, tab, offset]);
  const rows = useMemo(() => shaped?.rows ?? [], [shaped]);

  const columns = useMemo<Column<FaGridRow>[]>(() => {
    const cols: Column<FaGridRow>[] = [
      { title: "LINE", width: 34, text: (r) => r.label, color: (r) => (r.computed ? "dim" : gui && SUBTOTALS.has(r.key) ? "val" : "fg") },
    ];
    (shaped?.periods ?? []).forEach((p, i) =>
      cols.push({
        title: p.label,
        width: 10,
        align: "right",
        text: (r) => r.cells[i] ?? "",
        color: (r) => (r.cells[i]?.startsWith("-") ? "down" : r.flags[i] === "d" ? "warn" : gui && SUBTOTALS.has(r.key) ? "val" : "fg"),
      }),
    );
    return cols;
  }, [shaped, gui]);

  const latest = useLatest({ rows, shaped, tab, period, env, offset });
  useCsvExport(panelId, () => shaped && { name: `FA_${symbol}_${tab}_${period}`, header: ["LINE", ...shaped.periods.map((p) => p.label)], rows: rows.map((r) => [r.label, ...r.cells]) });

  usePanelRefresh(panelId, () => { void reload(true); });
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const g = grid.current;
        const { rows: cur, tab: t, env: en, offset: off } = latest.current;
        if (navKey(e, g, cur.length)) return true;
        const n = Number(e.key);
        if (n >= 1 && n <= STATEMENT_TABS.length) {
          setTab(STATEMENT_TABS[n - 1][0]);
          g?.moveTo(0);
          return true;
        }
        switch (e.key) {
          case "Tab": {
            const i = STATEMENT_TABS.findIndex(([k]) => k === t);
            setTab(STATEMENT_TABS[(i + (e.shiftKey ? STATEMENT_TABS.length - 1 : 1)) % STATEMENT_TABS.length][0]);
            return true;
          }
          case "a":
          case "q":
            setPeriod(e.key === "a" ? "A" : "Q");
            setOffset(0);
            return true;
          case "h":
          case "ArrowLeft":
            // Older periods: the newest column is on the left, like a filing.
            if (en) setOffset(Math.min(off + 1, Math.max(0, en.data.periods.length - 1)));
            return true;
          case "l":
          case "ArrowRight":
            setOffset(Math.max(0, off - 1));
            return true;
        }
        return false;
      }),
    [panelId, latest],
  );

  const d = env?.data;
  const cur = rows[sel] ?? rows[0];
  const cols = shaped?.periods ?? [];
  const newest = cols[0];
  const anyDerived = cols.some((p) => p.derived);
  // A plain failure with nothing to show yet gets the shared error note. Key-required and "US filers only" are not
  // failures (they have their own wording), and when older data is on screen ErrorLine says "SHOWING THE LAST DATA".
  const failedNote = !!error && !env && !isKeyRequired(error) && error.message !== US_ONLY;
  return (
    <div className="fn fa">
      <Header
        title={`FA ${symbol}${d?.name ? ` · ${d.name.toUpperCase()}` : ""}`}
        env={env}
        loading={loading}
        extra={d && ` · ${d.period === "A" ? "ANNUAL" : "QUARTERLY"} · ${unitNote(cur?.unit ?? "USD")} · ${d.currency}`}
        keys="1-3/TAB STATEMENT · A/Q PERIOD · H/L SCROLL · J/K MOVE · E CSV · F5 REFRESH"
      />
      {/* GUI: the toolbar buttons already switch statements, so the numbered strip (a duplicate) is hidden by CSS and
          this line says which statement and which unit the numbers are in. */}
      {gui && d && (
        <div className="fa-which" data-testid="fa-which">
          {STATEMENT_TABS.find(([k]) => k === tab)?.[1]} · figures in {unitNote(cur?.unit ?? "USD").toLowerCase()}
        </div>
      )}
      <div className="tabs">
        {STATEMENT_TABS.map(([k, label], i) => (
          <span key={k} className={k === tab ? "on" : "dim"}>
            {i + 1} {label}
          </span>
        ))}
      </div>
      <ErrorLine error={failedNote ? null : error} hasData={!!env} />
      {failedNote && (
        <PanelNote kind="error" hint={SEC_UA_RE.test(error.detail ?? "") ? SEC_UA_HINT : "F5 TO RETRY."}>
          {error.message}
          {error.detail && ` (${error.detail})`}
        </PanelNote>
      )}
      {loading && !env && !error && <PanelNote kind="loading">LOADING FA {symbol}…</PanelNote>}
      {d && rows.length === 0 && !error && (
        <PanelNote kind="empty" hint={gui ? undefined : "Press 1-3 for another statement, A / Q for annual or quarterly, or H to look at older periods."}>
          NO {tab} DATA REPORTED FOR {symbol}
        </PanelNote>
      )}
      <Grid ref={grid} columns={columns} rows={rows} onSelect={setSel} />
      <div className="summary dim fa-sum">
        {cur && newest ? `${cur.label} · ${newest.label} · ${cur.tags[0] ?? "—"}` : "SEC EDGAR XBRL"}
        {newest?.filed && ` · FILED ${newest.filed}`}
        {newest?.form && ` · ${newest.form}`}
        {anyDerived && <span className="warn"> · * DERIVED (YTD MINUS SHORTER YTD)</span>}
      </div>
    </div>
  );
}
