/** Financial analysis: income statement, balance sheet and cash flow from SEC XBRL company facts (annual or quarterly). */
import { useEffect, useMemo, useRef, useState } from "react";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { registerPanelKeys } from "../keys/panelKeys";
import { secApi } from "../net/api";
import { navKey, useLatest } from "./quoteRows";
import type { FunctionProps } from "./registry";
import { ErrorLine, Header, useEnvelope } from "./secPanel";
import { STATEMENT_TABS, faArgs, faRows, unitNote, type FaGridRow, type FaPayload, type FaPeriod, type StatementTab } from "./secTables";
import { useCsvExport } from "./tableExport";

const MAX_COLS = 12;

export default function FA({ panelId, security, args }: FunctionProps) {
  const symbol = security!.symbol;
  const init = useMemo(() => faArgs(args), [args]);
  const [period, setPeriod] = useState<FaPeriod>(init.period);
  const [tab, setTab] = useState<StatementTab>(init.tab);
  const [offset, setOffset] = useState(0);
  const [sel, setSel] = useState(0);
  const grid = useRef<GridHandle>(null);

  const { env, error, loading, reload } = useEnvelope<FaPayload>(`${symbol}|${period}`, (fresh) => secApi.fa(symbol, period, fresh));
  const shaped = useMemo(() => (env ? faRows(env.data, tab, offset, MAX_COLS) : null), [env, tab, offset]);
  const rows = useMemo(() => shaped?.rows ?? [], [shaped]);

  const columns = useMemo<Column<FaGridRow>[]>(() => {
    const cols: Column<FaGridRow>[] = [
      { title: "LINE", width: 34, text: (r) => r.label, color: (r) => (r.computed ? "dim" : "fg") },
    ];
    (shaped?.periods ?? []).forEach((p, i) =>
      cols.push({
        title: p.label,
        width: 10,
        align: "right",
        text: (r) => r.cells[i] ?? "",
        color: (r) => (r.cells[i]?.startsWith("-") ? "down" : r.flags[i] === "d" ? "warn" : "fg"),
      }),
    );
    return cols;
  }, [shaped]);

  const latest = useLatest({ rows, shaped, tab, period, env, offset });
  useCsvExport(panelId, () => shaped && { name: `FA_${symbol}_${tab}_${period}`, header: ["LINE", ...shaped.periods.map((p) => p.label)], rows: rows.map((r) => [r.label, ...r.cells]) });

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
          case "F5":
            void reload(true);
            return true;
        }
        return false;
      }),
    [panelId, latest, reload],
  );

  const d = env?.data;
  const cur = rows[sel] ?? rows[0];
  const cols = shaped?.periods ?? [];
  const newest = cols[0];
  const anyDerived = cols.some((p) => p.derived);
  return (
    <div className="fn">
      <Header
        title={`FA ${symbol}${d?.name ? ` · ${d.name.toUpperCase()}` : ""}`}
        env={env}
        loading={loading}
        extra={d && ` · ${d.period === "A" ? "ANNUAL" : "QUARTERLY"} · ${unitNote(cur?.unit ?? "USD")} · ${d.currency}`}
        keys="1-3/TAB STATEMENT · A/Q PERIOD · H/L SCROLL · J/K MOVE · E CSV · F5 REFRESH"
      />
      <div className="tabs">
        {STATEMENT_TABS.map(([k, label], i) => (
          <span key={k} className={k === tab ? "on" : "dim"}>
            {i + 1} {label}
          </span>
        ))}
      </div>
      <ErrorLine error={error} hasData={!!env} />
      {d && rows.length === 0 && !error && <div className="warn">NO {tab} DATA REPORTED FOR {symbol}</div>}
      <Grid ref={grid} columns={columns} rows={rows} onSelect={setSel} />
      <div className="summary dim">
        {cur && newest ? `${cur.label} · ${newest.label} · ${cur.tags[0] ?? "—"}` : "SEC EDGAR XBRL"}
        {newest?.filed && ` · FILED ${newest.filed}`}
        {newest?.form && ` · ${newest.form}`}
        {anyDerived && <span className="warn"> · * DERIVED (YTD MINUS SHORTER YTD)</span>}
      </div>
    </div>
  );
}
