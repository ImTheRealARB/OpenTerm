/**
 * FSRC: ETF screener. Filters every US exchange-traded fund by yearly fee (expense ratio), size (total assets) and category.
 * Grammar: fsrcFilter.ts (`FSRC FEE<0.2 AUM>1B CAT=LARGE SORT=FEE`).
 *
 * The table is collected by the backend in the background (about 5,800 funds, a call each to Yahoo, so about half an hour the
 * first time, then a day of cache). The panel shows the rows loaded so far and says PARTIAL until the server reports it complete.
 * Keys: J/K move, Enter opens DES, C opens the price chart, E exports CSV, F5 asks the server again.
 */
import { useEffect, useMemo, useRef } from "react";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { fmtBig, fmtNum } from "../format";
import { navKey } from "../keys/gridNav";
import { registerPanelKeys } from "../keys/panelKeys";
import type { FsrcRow } from "../net/etfTypes";
import { navigate } from "../state/workspace";
import { useLatest } from "../state/useLatest";
import { parseFsrcFilter, screenFsrc } from "./fsrcFilter";
import { EnvStatus, ErrorLine } from "./panelStatus";
import { usePanelRefresh } from "./panelRefresh";
import type { FunctionProps } from "./registry";
import { gridCsv, useCsvExport } from "./tableExport";
import { useFsrc } from "./useFsrc";

const USAGE = "FSRC FEE<0.2 AUM>1B CAT=LARGE SORT=FEE";
/** A fee under 0.1% needs a third decimal to tell 0.03 from 0.09. */
const fmtFee = (v: number | null) => fmtNum(v, v != null && v < 0.1 ? 3 : 2);
const fmtInt = (n: number) => n.toLocaleString("en-US");

const COLUMNS: Column<FsrcRow>[] = [
  { title: "SYMBOL", width: 8, text: (r) => r[0], color: () => "acc" },
  { title: "NAME", width: 36, text: (r) => r[1], color: () => "dim" },
  { title: "FEE %", width: 7, align: "right", text: (r) => fmtFee(r[2]) },
  { title: "AUM", width: 9, align: "right", text: (r) => fmtBig(r[3]) },
  { title: "CATEGORY", width: 28, text: (r) => r[4] ?? "" },
  { title: "FAMILY", width: 30, text: (r) => r[5] ?? "", color: () => "dim" },
];

export default function FSRC({ panelId, args }: FunctionProps) {
  const { rows: all, env, error, loading, reload } = useFsrc();
  const grid = useRef<GridHandle>(null);
  const d = env?.data;
  const complete = d?.state === "complete";

  const filter = useMemo(() => parseFsrcFilter(args), [args]);
  const result = useMemo(() => screenFsrc(all, filter, complete), [all, filter, complete]);
  const rows = result.rows;
  const latest = useLatest(rows);

  useCsvExport(panelId, () => (all.length ? gridCsv(`FSRC_${args.join("_") || "ALL"}`, COLUMNS, rows) : null));
  usePanelRefresh(panelId, () => reload());
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const g = grid.current;
        const cur = latest.current;
        if (navKey(e, g, cur.length)) return true;
        const r = cur[g?.selected() ?? -1];
        switch (e.key) {
          case "Enter":
            if (r) navigate(panelId, { fn: "DES", security: { symbol: r[0] }, args: [] });
            return true;
          case "c":
            if (r) navigate(panelId, { fn: "GP", security: { symbol: r[0] }, args: [] });
            return true;
        }
        return false;
      }),
    [panelId, latest],
  );

  const waiting = d ? d.universe - d.loaded - d.nodata - d.failed : 0;
  return (
    <div className="fn">
      <div className="line">
        <span className="acc">FSRC</span>
        {d && (
          <>
            {" · "}
            {fmtInt(d.loaded)} OF {fmtInt(d.universe)} US <span data-term="ETF">ETFS</span> LOADED
            {d.partial ? <span className="warn"> · PARTIAL</span> : <span className="dim"> · COMPLETE</span>}
          </>
        )}
        {d && <span className="acc"> · {fmtInt(rows.length)} MATCH</span>}
        {result.terms.length > 0 && ` · ${result.terms.join(" ")}`}
        {d && <span className="dim"> · {filter.sort ? `SORT ${filter.sort.key} ${filter.sort.dir === 1 ? "ASCENDING" : "DESCENDING"}` : "LARGEST FIRST"}</span>}
        {d && result.terms.length === 0 && (
          <span className="dim"> · NO FILTER · TRY <span data-term="EXPENSE RATIO">FEE</span>&lt;0.2 <span data-term="AUM">AUM</span>&gt;1B CAT=LARGE</span>
        )}
        <EnvStatus env={env} loading={loading} />
        <span className="dim legend"> · J/K MOVE · ENTER DES · C CHART · E CSV · F5 REFRESH</span>
      </div>
      {d?.partial && (
        <div className="warn" data-testid="fsrc-partial">
          {d.state === "paused" ? "PAUSED, WAITING OUT A YAHOO LIMIT. " : ""}
          {waiting > 0 ? `${fmtInt(waiting)} FUNDS STILL TO LOAD: A FUND NOT LISTED YET MAY STILL MATCH. ` : ""}
          {d.note ?? ""}
        </div>
      )}
      {d && d.nodata + d.failed > 0 && (
        <div className="dim">
          {d.nodata > 0 && `${fmtInt(d.nodata)} ${d.nodata === 1 ? "FUND HAS" : "FUNDS HAVE"} NO FUND DATA AT YAHOO (NOT SHOWN)`}
          {d.nodata > 0 && d.failed > 0 && " · "}
          {d.failed > 0 && <span className="warn">{fmtInt(d.failed)} COULD NOT BE LOADED (TRIED AGAIN IN AN HOUR)</span>}
        </div>
      )}
      {result.errors.length > 0 && <div className="err">{result.errors.join(" · ")} · EXAMPLE: {USAGE}</div>}
      <ErrorLine error={error} hasData={all.length > 0} />
      {d && !rows.length && !result.errors.length && (
        <div className="warn">{d.partial ? "NO LOADED FUND MATCHES YET" : "NO FUND MATCHES THE FILTER"}</div>
      )}
      {!d && !error && <div className="dim">LOADING THE ETF LIST…</div>}
      <Grid ref={grid} columns={COLUMNS} rows={rows} />
    </div>
  );
}
