/** Holders: ownership breakdown, top institutional holders and top funds (Yahoo Finance, 13F-based). */
import { useEffect, useMemo, useRef } from "react";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { fmtBig } from "../format";
import { registerPanelKeys } from "../keys/panelKeys";
import { secApi } from "../net/api";
import { navKey, useLatest } from "./quoteRows";
import type { FunctionProps } from "./registry";
import { ErrorLine, Header, useEnvelope } from "./secPanel";
import { fmtFrac, fmtShares, holderRows, type HolderRow, type HoldersPayload } from "./secTables";
import { gridCsv, useCsvExport } from "./tableExport";

const COLUMNS: Column<HolderRow>[] = [
  { title: "HOLDER", width: 40, text: (r) => r.section ?? r.holder, color: (r) => (r.section ? "acc" : "fg") },
  { title: "% HELD", width: 8, align: "right", text: (r) => r.pct },
  { title: "SHARES", width: 15, align: "right", text: (r) => (r.section || r.shares == null ? "" : fmtShares(r.shares)) },
  { title: "VALUE", width: 8, align: "right", text: (r) => (r.value == null ? "" : fmtBig(r.value)) },
  { title: "% CHG", width: 8, align: "right", text: (r) => (r.pct_change == null ? "" : fmtFrac(r.pct_change)), color: (r) => ((r.pct_change ?? 0) < 0 ? "down" : (r.pct_change ?? 0) > 0 ? "up" : "fg") },
  { title: "REPORTED", width: 10, text: (r) => r.date, color: () => "dim" },
];

export default function HDS({ panelId, security }: FunctionProps) {
  const symbol = security!.symbol;
  const grid = useRef<GridHandle>(null);
  const { env, error, loading, reload } = useEnvelope<HoldersPayload>(symbol, (fresh) => secApi.holders(symbol, fresh));
  const rows = useMemo(() => (env ? holderRows(env.data) : []), [env]);
  const latest = useLatest({ rows });
  useCsvExport(panelId, () => gridCsv(`HDS_${symbol}`, COLUMNS, rows.filter((r) => !r.section)));
  const isHeader = (i: number) => !!latest.current.rows[i]?.section;

  // Row 0 is a section header: start the cursor on the first data row once a payload arrives.
  useEffect(() => {
    if (env) grid.current?.moveTo(1);
  }, [env]);

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const g = grid.current;
        const cur = latest.current.rows;
        if (navKey(e, g, cur.length, isHeader)) return true;
        switch (e.key) {
          case "F5":
            void reload(true);
            return true;
        }
        return false;
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [panelId, latest, reload, symbol],
  );

  const d = env?.data;
  return (
    <div className="fn">
      <Header
        title={`HDS ${symbol}`}
        env={env}
        loading={loading}
        extra={d && ` · ${d.institutions.length} INSTITUTIONS · ${d.funds.length} FUNDS`}
        keys="J/K MOVE · E CSV · F5 REFRESH"
      />
      <ErrorLine error={error} hasData={!!env} />
      {d && d.institutions.length === 0 && d.funds.length === 0 && !error && <div className="warn">NO HOLDER LISTS REPORTED FOR {symbol}</div>}
      <Grid ref={grid} columns={COLUMNS} rows={rows} initialSelected={1} />
      <div className="summary dim">13F FILINGS ARE QUARTERLY AND REPORTED UP TO 45 DAYS AFTER QUARTER END · PERCENTAGES ARE OF SHARES OUTSTANDING</div>
    </div>
  );
}
