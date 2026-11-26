/**
 * MRR (Phase 27): index members ranked by how much each added to or took from the index over a period.
 * `MRR SPX 1M`. Weights come from the proxy ETF's SEC N-PORT filing (the MEMB function); contribution = weight x return.
 * NIFTY lists have no weights, so they show returns only (said on screen). Keys: J/K move, Enter GP, E CSV.
 */
import { useMemo, useRef, useEffect } from "react";
import { execute } from "../command/execute";
import { Grid, type CellColor, type Column, type GridHandle } from "../components/Grid";
import { PanelNote } from "../components/PanelNote";
import { fmtNum, fmtPct, fmtPrice } from "../format";
import { navKey } from "../keys/gridNav";
import { registerPanelKeys } from "../keys/panelKeys";
import { scanApi } from "../net/scanApi";
import type { MrrResult, MrrRow } from "../net/types";
import { useLatest } from "../state/useLatest";
import type { FunctionProps } from "./registry";
import { parseMrrArgs, UNIVERSES } from "./scanArgs";
import { gridCsv, useCsvExport } from "./tableExport";
import { useTaskPoll } from "./useTaskPoll";

const sign = (v: number | null): CellColor => (v == null || v === 0 ? "fg" : v > 0 ? "up" : "down");
const COLS: Column<MrrRow>[] = [
  { title: "SYMBOL", width: 12, text: (r) => r.symbol, color: () => "acc" },
  { title: "LAST", width: 11, align: "right", text: (r) => fmtPrice(r.last) },
  { title: "RETURN", width: 9, align: "right", text: (r) => (r.return == null ? "—" : fmtPct(r.return * 100)), color: (r) => sign(r.return) },
  { title: "WEIGHT", width: 8, align: "right", text: (r) => (r.weight == null ? "—" : fmtPct(r.weight * 100)), color: () => "dim" },
  { title: "CONTRIB PTS%", width: 13, align: "right", text: (r) => (r.contrib == null ? "—" : fmtNum(r.contrib * 100, 3)), color: (r) => sign(r.contrib) },
  { title: "NOTE", width: 40, text: (r) => r.note ?? "", color: () => "err" },
];

export default function MRR({ panelId, args }: FunctionProps) {
  const parsed = useMemo(() => parseMrrArgs(args), [args]);
  const grid = useRef<GridHandle>(null);
  const { task, error } = useTaskPoll<MrrResult>(parsed.ok ? () => scanApi.mrr(parsed.universe, parsed.period) : null, scanApi.mrrTask, parsed);
  const res = task?.state === "done" ? task.result : null;
  const latest = useLatest({ res });
  useCsvExport(panelId, () => (latest.current.res ? gridCsv("MRR", COLS, latest.current.res.rows) : null));
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const r = latest.current.res;
        if (!r) return false;
        if (navKey(e, grid.current, r.rows.length)) return true;
        if (e.key === "Enter") {
          const row = r.rows[grid.current?.selected() ?? 0];
          if (row) execute(`${row.symbol} GP 1Y`, { newPanel: true });
          return true;
        }
        return false;
      }),
    [panelId, latest],
  );
  return (
    <div className="fn mrr">
      <div className="line">
        <span className="acc">MRR </span>
        {parsed.ok ? `${parsed.universe} · ${parsed.period}` : ""}
        {task?.source ? <span className="dim"> · {task.source}</span> : null}
      </div>
      {!parsed.ok && <PanelNote kind="error" hint={`UNIVERSE: ${UNIVERSES}`}>{parsed.error}</PanelNote>}
      {error && <PanelNote kind="error">ERR: {error}</PanelNote>}
      {task?.state === "error" && <PanelNote kind="error">ERR: {task.error}</PanelNote>}
      {task && task.state === "fetching" && (
        <div className="line"><span className="acc">DOWNLOADING BARS </span>{task.done} OF {task.total} <span className="dim">· YAHOO LIMITS SPEED</span></div>
      )}
      {res && (
        <>
          <div className="line">
            <span className="up">{res.up} UP</span> · <span className="down">{res.down} DOWN</span>
            {res.weighted && res.sum_contrib != null ? <> · SUM OF CONTRIBUTIONS <span className={sign(res.sum_contrib)}>{fmtNum(res.sum_contrib * 100, 2)} PTS%</span></> : <span className="warn"> · NO INDEX WEIGHTS FOR THIS LIST: RETURNS ONLY</span>}
            {res.failed ? <span className="warn"> · PARTIAL: {res.failed} WITHOUT DATA</span> : null}
            {res.fixtures ? <span className="dim"> · RECORDED FIXTURE DATA</span> : null}
          </div>
          <div className="dim legend">J/K MOVE · ENTER GP · E CSV · CONTRIB = WEIGHT x RETURN, IN PERCENTAGE POINTS OF THE INDEX</div>
          <Grid ref={grid} columns={COLS} rows={res.rows} />
        </>
      )}
    </div>
  );
}
