/**
 * OSCAN (Phase 28): option scan over a universe, from the chain recorder's own snapshots only (no live chain downloads).
 * `OSCAN WL:TECH IVR>50 EM>5 OI>1000 PCR>1.2`. IVR = IV rank in percent, EM = nearest-expiry straddle move in percent,
 * OI = total open interest, PCR = put OI / call OI. A symbol with no snapshot is listed as NOT RECORDED. Keys: J/K, Enter OMON, E CSV.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { execute } from "../command/execute";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { PanelNote } from "../components/PanelNote";
import { fmtNum, fmtPct, fmtPrice } from "../format";
import { navKey } from "../keys/gridNav";
import { registerPanelKeys } from "../keys/panelKeys";
import { optionsRecApi } from "../net/optionsRecApi";
import type { OptionRecStats, OptionScanResult } from "../net/types";
import { useLatest } from "../state/useLatest";
import { parseOscanArgs } from "./oscanArgs";
import type { FunctionProps } from "./registry";
import { gridCsv, useCsvExport } from "./tableExport";

const pct = (v: number | null) => (v == null ? "—" : fmtPct(v * 100));
const COLS: Column<OptionRecStats>[] = [
  { title: "SYMBOL", width: 12, text: (r) => r.symbol, color: () => "acc" },
  { title: "SPOT", width: 10, align: "right", text: (r) => fmtPrice(r.spot) },
  { title: "ATM IV", width: 8, align: "right", text: (r) => pct(r.atm_iv) },
  { title: "IV RANK", width: 8, align: "right", text: (r) => pct(r.iv_rank) },
  { title: "IV PCTL", width: 8, align: "right", text: (r) => pct(r.iv_percentile) },
  { title: "EM %", width: 7, align: "right", text: (r) => (r.em_pct == null ? "—" : fmtNum(r.em_pct, 1)) },
  { title: "OI", width: 11, align: "right", text: (r) => fmtNum(r.oi, 0) },
  { title: "PCR", width: 6, align: "right", text: (r) => (r.pcr == null ? "—" : fmtNum(r.pcr, 2)) },
  { title: "DAYS", width: 5, align: "right", text: (r) => String(r.days_recorded), color: () => "dim" },
  { title: "AS OF", width: 11, text: (r) => r.day, color: () => "dim" },
];

export default function OSCAN({ panelId, args }: FunctionProps) {
  const parsed = useMemo(() => parseOscanArgs(args), [args]);
  const grid = useRef<GridHandle>(null);
  const [res, setRes] = useState<OptionScanResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const latest = useLatest({ res });
  useEffect(() => {
    if (!parsed.ok) return;
    let alive = true;
    setRes(null);
    setError(null);
    optionsRecApi.scan(parsed.universe, parsed.filter).then(
      (r) => { if (alive) setRes(r); },
      (e: Error) => { if (alive) setError(e.message); },
    );
    return () => { alive = false; };
  }, [parsed]);
  useCsvExport(panelId, () => (latest.current.res ? gridCsv("OSCAN", COLS, latest.current.res.rows) : null));
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const r = latest.current.res;
        if (!r) return false;
        if (navKey(e, grid.current, r.rows.length)) return true;
        if (e.key === "Enter") {
          const row = r.rows[grid.current?.selected() ?? 0];
          if (row) execute(`${row.symbol} OMON`, { newPanel: true });
          return true;
        }
        return false;
      }),
    [panelId, latest],
  );
  return (
    <div className="fn oscan">
      <div className="line">
        <span className="acc">OSCAN </span>
        {parsed.ok ? `${parsed.universe} ${parsed.filter}` : ""}
        {res ? <span className="dim"> · {res.universe}</span> : null}
      </div>
      {!parsed.ok && <PanelNote kind="error">{parsed.error}</PanelNote>}
      {error && <PanelNote kind="error">ERR: {error}</PanelNote>}
      {parsed.ok && !res && !error && <div className="line dim">READING THE RECORDED SNAPSHOTS</div>}
      {res && (
        <>
          <div className="line">
            <span className="up">{res.matched} MATCH</span> OF {res.checked} RECORDED
            {res.not_recorded.length ? <span className="warn"> · {res.not_recorded.length} NOT RECORDED: {res.not_recorded.slice(0, 12).join(" ")}{res.not_recorded.length > 12 ? " …" : ""}</span> : null}
          </div>
          <div className="dim legend">{res.label} · {res.note}</div>
          <div className="dim legend">J/K MOVE · ENTER OMON · E CSV · IVR AND EM IN PERCENT · PCR = PUT OI / CALL OI</div>
          <Grid ref={grid} columns={COLS} rows={res.rows} />
        </>
      )}
    </div>
  );
}
